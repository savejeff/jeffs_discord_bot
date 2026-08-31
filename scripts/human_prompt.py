#!/usr/bin/env python3
"""Serve a blocking browser prompt and report the selected response."""

from __future__ import annotations

import argparse
import html
import io
import json
import math
import os
import secrets
import shutil
import struct
import subprocess
import sys
import threading
import urllib.parse
import wave
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DEFAULT_MESSAGE = "Please perform the requested action."
DEFAULT_TITLE = "Action required"
DEFAULT_WIDTH = 560
DEFAULT_HEIGHT = 500
MAX_OPTIONS = 20
MAX_OPTION_LENGTH = 100
MAX_RESPONSE_LENGTH = 2000


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description=(
			"Open a local web prompt and wait for a button or free-form response. "
			"The URL and selected response are written as JSON to stdout."
		),
	)
	parser.add_argument(
		"message",
		nargs="?",
		default=DEFAULT_MESSAGE,
		help="Message shown to the user.",
	)
	parser.add_argument(
		"--title",
		default=DEFAULT_TITLE,
		help=f"Prompt title. Default: {DEFAULT_TITLE!r}.",
	)
	parser.add_argument(
		"--complete-label",
		default="Completed",
		help="Successful-response label used when no --option is supplied.",
	)
	parser.add_argument(
		"--reject-label",
		default="Rejected",
		help="Rejected-response label used when no --option is supplied.",
	)
	parser.add_argument(
		"--option",
		action="append",
		default=[],
		metavar="LABEL",
		help=(
			"Custom response button label. Repeat for any number of choices. "
			"Supplying one or more options replaces Completed/Rejected."
		),
	)
	parser.add_argument(
		"--other-label",
		default="Other response",
		help="Label shown above the free-form response field.",
	)
	parser.add_argument(
		"--other-submit-label",
		default="Submit response",
		help="Label for the free-form response submit button.",
	)
	parser.add_argument(
		"--no-other-response",
		action="store_true",
		help="Hide the free-form response field.",
	)
	parser.add_argument(
		"--host",
		default="127.0.0.1",
		help="Address on which to serve the prompt. Default: 127.0.0.1.",
	)
	parser.add_argument(
		"--port",
		type=int,
		default=8765,
		help="TCP port on which to serve the prompt. Default: 8765.",
	)
	parser.add_argument(
		"--width",
		type=int,
		default=DEFAULT_WIDTH,
		help=f"Requested browser-window width. Default: {DEFAULT_WIDTH}.",
	)
	parser.add_argument(
		"--height",
		type=int,
		default=DEFAULT_HEIGHT,
		help=f"Requested browser-window height. Default: {DEFAULT_HEIGHT}.",
	)
	parser.add_argument(
		"--no-browser",
		action="store_true",
		help="Serve and print the URL without opening a browser window.",
	)
	parser.add_argument(
		"--no-alert",
		action="store_true",
		help="Disable the system and browser alert sounds.",
	)
	return parser


def response_options(args: argparse.Namespace) -> list[tuple[str, str]]:
	if args.option:
		return [("selected", label) for label in args.option]
	return [
		("rejected", args.reject_label),
		("completed", args.complete_label),
	]


def build_alert_wav() -> bytes:
	sample_rate = 16000
	duration_seconds = 0.22
	frequency_hz = 880.0
	sample_count = int(sample_rate * duration_seconds)
	frames = bytearray()
	for sample_index in range(sample_count):
		time_seconds = sample_index / sample_rate
		envelope = min(1.0, sample_index / 160.0)
		envelope *= min(1.0, (sample_count - sample_index) / 320.0)
		value = int(11000 * envelope * math.sin(2.0 * math.pi * frequency_hz * time_seconds))
		frames.extend(struct.pack("<h", value))

	buffer = io.BytesIO()
	with wave.open(buffer, "wb") as wav_file:
		wav_file.setnchannels(1)
		wav_file.setsampwidth(2)
		wav_file.setframerate(sample_rate)
		wav_file.writeframes(frames)
	return buffer.getvalue()


def option_buttons(args: argparse.Namespace) -> str:
	options = response_options(args)
	buttons = []
	for index, (status, label) in enumerate(options):
		css_class = "complete" if status == "completed" else "choice"
		if status == "rejected":
			css_class = "reject"
		if args.option:
			button_name = "choice"
			button_value = str(index)
		else:
			button_name = "status"
			button_value = status
		buttons.append(
			f'<button class="{css_class}" name="{button_name}" '
			f'value="{html.escape(button_value, quote=True)}">'
			f'{html.escape(label)}</button>'
		)
	return "\n\t\t\t".join(buttons)


def other_response_form(args: argparse.Namespace, token: str) -> str:
	if args.no_other_response:
		return ""
	other_label = html.escape(args.other_label)
	submit_label = html.escape(args.other_submit_label)
	return f"""
		<section class="other">
			<label for="response-text">{other_label}</label>
			<form action="/respond" method="post" id="other-form">
				<input type="hidden" name="token" value="{token}">
				<textarea id="response-text" name="response_text" maxlength="{MAX_RESPONSE_LENGTH}"
					rows="3" placeholder="Type a response..."></textarea>
				<button class="submit" type="submit" id="other-submit" disabled>{submit_label}</button>
			</form>
		</section>"""


def prompt_page(args: argparse.Namespace, token: str) -> bytes:
	title = html.escape(args.title)
	message = html.escape(args.message).replace("\n", "<br>")
	escaped_token = html.escape(token, quote=True)
	buttons = option_buttons(args)
	other_form = other_response_form(args, escaped_token)
	audio_markup = "" if args.no_alert else '<audio id="prompt-alert" src="/alert.wav" autoplay></audio>'
	page = f"""<!doctype html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>{title}</title>
	<style>
		:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
		* {{ box-sizing: border-box; }}
		body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
			padding: 1rem; background: #18202b; color: #f5f7fa; }}
		main {{ width: min(100%, 520px); padding: 1.6rem; border: 1px solid #526173;
			border-radius: 12px; background: #242f3d; box-shadow: 0 16px 48px #0008; }}
		h1 {{ margin: 0 0 .85rem; font-size: 1.4rem; }}
		.message {{ margin: 0 0 1.4rem; line-height: 1.5; }}
		.choices {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: .65rem; }}
		button {{ border: 0; border-radius: 7px; padding: .68rem 1rem;
			font: inherit; font-weight: 650; cursor: pointer; }}
		button:focus-visible, textarea:focus-visible {{ outline: 3px solid #72a7ff; outline-offset: 2px; }}
		.reject {{ background: #687586; color: white; }}
		.complete {{ background: #2f8f55; color: white; }}
		.choice {{ background: #3378bd; color: white; }}
		.submit {{ align-self: flex-end; background: #2f8f55; color: white; }}
		button:disabled {{ cursor: not-allowed; opacity: .45; }}
		.other {{ margin-top: 1.3rem; padding-top: 1.2rem; border-top: 1px solid #526173; }}
		.other label {{ display: block; margin-bottom: .55rem; font-weight: 650; }}
		.other form {{ display: flex; flex-direction: column; gap: .65rem; }}
		textarea {{ width: 100%; resize: vertical; min-height: 4.5rem; max-height: 10rem;
			border: 1px solid #65758a; border-radius: 7px; padding: .65rem;
			background: #18202b; color: inherit; font: inherit; }}
	</style>
</head>
<body>
	<main>
		<h1>{title}</h1>
		<p class="message">{message}</p>
		<form class="choices" action="/respond" method="post">
			<input type="hidden" name="token" value="{escaped_token}">
			{buttons}
		</form>
		{other_form}
	</main>
	{audio_markup}
	<script>
		const responseText = document.getElementById('response-text');
		const responseSubmit = document.getElementById('other-submit');
		if (responseText && responseSubmit) {{
			const updateSubmit = () => responseSubmit.disabled = responseText.value.trim().length === 0;
			responseText.addEventListener('input', updateSubmit);
			responseText.addEventListener('keydown', event => {{
				if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !responseSubmit.disabled) {{
					event.preventDefault();
					document.getElementById('other-form').requestSubmit();
				}}
			}});
			updateSubmit();
		}}
		const promptAlert = document.getElementById('prompt-alert');
		if (promptAlert) {{
			promptAlert.play().catch(() => {{ document.title = '🔔 ' + document.title; }});
		}}
	</script>
</body>
</html>"""
	return page.encode("utf-8")


def result_page(response: dict[str, object]) -> bytes:
	status = str(response["status"])
	if status == "completed":
		label = "Completed"
	elif status == "rejected":
		label = "Rejected"
	elif status == "other":
		label = "Response submitted"
	else:
		label = "Selection submitted"
	detail = html.escape(str(response.get("response", "")))
	return f"""<!doctype html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>{label}</title>
	<style>
		:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
		body {{ max-width: 34rem; margin: 3rem auto; padding: 1rem; }}
		p {{ overflow-wrap: anywhere; }}
	</style>
</head>
<body>
	<h1>{label}</h1>
	<p>{detail}</p>
	<p>The response was recorded. You may close this window.</p>
	<script>setTimeout(() => window.close(), 1200);</script>
</body>
</html>""".encode("utf-8")


def validate_args(args: argparse.Namespace) -> str | None:
	if not 0 <= args.port <= 65535:
		return "--port must be between 0 and 65535"
	if args.width < 400 or args.width > 2000:
		return "--width must be between 400 and 2000"
	if args.height < 320 or args.height > 1600:
		return "--height must be between 320 and 1600"
	if len(args.option) > MAX_OPTIONS:
		return f"no more than {MAX_OPTIONS} --option values are supported"
	for label in args.option:
		if not label.strip():
			return "--option labels must not be empty"
		if len(label) > MAX_OPTION_LENGTH:
			return f"--option labels must not exceed {MAX_OPTION_LENGTH} characters"
	return None


def browser_candidates() -> list[tuple[str, Path]]:
	candidates = []
	seen = set()
	known_locations = [
		("edge", Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe"),
		("edge", Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe"),
		("edge", Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe"),
		("chrome", Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe"),
		("chrome", Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe"),
		("chrome", Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"),
	]
	for browser_name, executable in known_locations:
		if executable.is_file() and executable not in seen:
			seen.add(executable)
			candidates.append((browser_name, executable))
	for browser_name, command_name in (("edge", "msedge"), ("chrome", "chrome")):
		located = shutil.which(command_name)
		if located:
			executable = Path(located)
			if executable not in seen:
				seen.add(executable)
				candidates.append((browser_name, executable))
	return candidates


def browser_launch_allowed() -> bool:
	if os.name != "nt":
		return True
	try:
		import ctypes

		buffer_size = ctypes.c_ulong(256)
		username_buffer = ctypes.create_unicode_buffer(buffer_size.value)
		if not ctypes.windll.advapi32.GetUserNameW(
			username_buffer,
			ctypes.byref(buffer_size),
		):
			return True
		process_username = username_buffer.value
		desktop_username = os.environ.get("USERNAME", "")
		if desktop_username and process_username.casefold() != desktop_username.casefold():
			print(
				"human_prompt: browser auto-open skipped because the process is not "
				"running as the interactive desktop user; use an approved GUI launch "
				"or open the reported URL",
				file=sys.stderr,
				flush=True,
			)
			return False
	except Exception:
		return True
	return True


def centered_window_position(width: int, height: int) -> tuple[int, int]:
	if os.name != "nt":
		return 80, 80
	try:
		import ctypes

		user32 = ctypes.windll.user32
		try:
			user32.SetProcessDPIAware()
		except Exception:
			pass
		screen_width = int(user32.GetSystemMetrics(0))
		screen_height = int(user32.GetSystemMetrics(1))
		return max(0, (screen_width - width) // 2), max(0, (screen_height - height) // 2)
	except Exception:
		return 80, 80


def open_browser_window(url: str, args: argparse.Namespace) -> str | None:
	if args.no_browser or not browser_launch_allowed():
		return None

	x, y = centered_window_position(args.width, args.height)
	for browser_name, executable in browser_candidates():
		command = [
			str(executable),
			f"--app={url}",
			"--new-window",
			f"--window-size={args.width},{args.height}",
			f"--window-position={x},{y}",
		]
		try:
			creation_flags = 0
			if os.name == "nt":
				creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
			subprocess.Popen(
				command,
				stdin=subprocess.DEVNULL,
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
				close_fds=True,
				creationflags=creation_flags,
			)
			return browser_name
		except OSError:
			continue

	try:
		if webbrowser.open_new(url):
			return "default"
	except webbrowser.Error:
		pass
	return None


def play_system_alert(disabled: bool) -> bool:
	if disabled or os.name != "nt":
		return False
	try:
		import winsound

		winsound.PlaySound(
			"SystemExclamation",
			winsound.SND_ALIAS | winsound.SND_ASYNC,
		)
		return True
	except (ImportError, RuntimeError):
		return False


def parse_response(
	fields: dict[str, list[str]],
	args: argparse.Namespace,
) -> dict[str, object] | None:
	response_text = fields.get("response_text", [""])[0].strip()
	if response_text:
		if args.no_other_response or len(response_text) > MAX_RESPONSE_LENGTH:
			return None
		return {"status": "other", "response": response_text}

	if args.option:
		choice_text = fields.get("choice", [""])[0]
		try:
			choice_index = int(choice_text)
		except ValueError:
			return None
		if choice_index < 0 or choice_index >= len(args.option):
			return None
		return {
			"status": "selected",
			"response": args.option[choice_index],
			"option_index": choice_index,
		}

	status = fields.get("status", [""])[0]
	if status == "completed":
		return {"status": "completed", "response": args.complete_label}
	if status == "rejected":
		return {"status": "rejected", "response": args.reject_label}
	return None


def serve_prompt(args: argparse.Namespace) -> tuple[dict[str, object], str, str | None, bool]:
	token = secrets.token_urlsafe(24)
	response_event = threading.Event()
	response_lock = threading.Lock()
	selected_response: dict[str, object] = {"status": "dismissed", "response": ""}
	page = prompt_page(args, token)
	alert_wav = build_alert_wav()

	class PromptHandler(BaseHTTPRequestHandler):
		def send_content(self, body: bytes, content_type: str, status: int = 200) -> None:
			self.send_response(status)
			self.send_header("Content-Type", content_type)
			self.send_header("Content-Length", str(len(body)))
			self.send_header("Cache-Control", "no-store")
			self.end_headers()
			self.wfile.write(body)

		def do_GET(self) -> None:
			path = urllib.parse.urlsplit(self.path).path
			if path == "/":
				self.send_content(page, "text/html; charset=utf-8")
				return
			if path == "/alert.wav" and not args.no_alert:
				self.send_content(alert_wav, "audio/wav")
				return
			if path == "/favicon.ico":
				self.send_response(204)
				self.end_headers()
				return
			self.send_error(404)

		def do_POST(self) -> None:
			if urllib.parse.urlsplit(self.path).path != "/respond":
				self.send_error(404)
				return
			try:
				content_length = int(self.headers.get("Content-Length", "0"))
			except ValueError:
				self.send_error(400)
				return
			if content_length > 16384:
				self.send_error(413)
				return
			try:
				fields = urllib.parse.parse_qs(
					self.rfile.read(content_length).decode("utf-8"),
					keep_blank_values=True,
				)
			except UnicodeDecodeError:
				self.send_error(400)
				return
			request_token = fields.get("token", [""])[0]
			response = parse_response(fields, args)
			if request_token != token or response is None:
				self.send_error(400)
				return

			with response_lock:
				if selected_response["status"] == "dismissed":
					selected_response.clear()
					selected_response.update(response)
				recorded_response = dict(selected_response)
			try:
				self.send_content(result_page(recorded_response), "text/html; charset=utf-8")
			except (BrokenPipeError, ConnectionResetError):
				pass
			finally:
				response_event.set()

		def log_message(self, _format: str, *_args: object) -> None:
			return

	try:
		server = ThreadingHTTPServer((args.host, args.port), PromptHandler)
	except OSError as exc:
		raise RuntimeError(
			f"unable to listen on {args.host}:{args.port}: {exc}"
		) from exc

	bound_host, bound_port = server.server_address[:2]
	server.timeout = 0.25
	display_host = "127.0.0.1" if bound_host in {"0.0.0.0", "::"} else bound_host
	url = f"http://{display_host}:{bound_port}/"
	browser_name = open_browser_window(url, args)
	alert_played = play_system_alert(args.no_alert)
	print(
		json.dumps(
			{
				"status": "waiting",
				"url": url,
				"browser": browser_name,
				"alert_played": alert_played,
			}
		),
		flush=True,
	)

	try:
		while not response_event.is_set():
			server.handle_request()
	finally:
		server.server_close()

	return dict(selected_response), url, browser_name, alert_played


def main() -> int:
	args = build_parser().parse_args()
	validation_error = validate_args(args)
	if validation_error:
		print(f"human_prompt: {validation_error}", file=sys.stderr)
		return 2

	try:
		response, url, browser_name, alert_played = serve_prompt(args)
	except Exception as exc:
		print(f"human_prompt: {exc}", file=sys.stderr)
		return 2

	result = dict(response)
	result.update(
		{
			"url": url,
			"browser": browser_name,
			"alert_played": alert_played,
		}
	)
	print(json.dumps(result, ensure_ascii=False), flush=True)
	return 1 if response["status"] == "rejected" else 0


if __name__ == "__main__":
	raise SystemExit(main())
