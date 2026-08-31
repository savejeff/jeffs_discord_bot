# Human prompt helper

## Core functionality

`human_prompt.py` serves a temporary loopback web page, tries to open it as a small browser window, alerts the user, and blocks until the user selects a response or enters text. It writes machine-readable JSON status and result lines to stdout. The script uses only the Python standard library.

Use it when an automated workflow needs an explicit local human action or choice. It has no timeout and should not replace ordinary terminal interaction when the user is already present.

## Usage

Request the default Completed/Rejected response:

```powershell
python toolbox\general\human_prompt\human_prompt.py "Connect the RS485 adapter, then select Completed."
```

Offer custom choices and allow a free-form answer:

```powershell
python toolbox\general\human_prompt\human_prompt.py "Which target should be tested?" --title "Target selection" --option "Board A" --option "Board B"
```

Serve without attempting to launch a browser:

```powershell
python toolbox\general\human_prompt\human_prompt.py "Open the printed URL." --no-browser --no-alert
```

## Parameters

| Parameter | Meaning |
|---|---|
| `message` | Optional prompt text; default `Please perform the requested action.` |
| `--title TEXT` | Window/page title; default `Action required`. |
| `--complete-label TEXT` | Positive button label without custom options; default `Completed`. |
| `--reject-label TEXT` | Negative button label without custom options; default `Rejected`. |
| `--option LABEL` | Custom button label; repeat up to 20 times. Any option replaces the default pair. |
| `--other-label TEXT` | Label above the free-form field; default `Other response`. |
| `--other-submit-label TEXT` | Free-form submit label; default `Submit response`. |
| `--no-other-response` | Hide the free-form response field. |
| `--host ADDRESS` | HTTP bind address; default `127.0.0.1`. |
| `--port N` | TCP port; default `8765`; `0` requests an ephemeral port. |
| `--width N` | Browser window width, 400 through 2000; default `560`. |
| `--height N` | Browser window height, 320 through 1600; default `500`. |
| `--no-browser` | Do not auto-open a browser; print the URL only. |
| `--no-alert` | Disable both system and page alert sounds. |

Option labels are limited to 100 characters and free-form responses to 2000 characters.

## Output and safety

The first JSON line reports `status: waiting`, the URL, browser choice, and whether a system alert played. The final JSON line reports the selected status/response plus the same connection metadata. A rejected default response exits `1`; accepted, selected, or free-form responses exit `0`; validation/server errors exit `2`.

The form uses a per-run token and binds to loopback by default. Changing `--host` to a non-loopback interface exposes an unauthenticated action prompt on that network and should be avoided unless access controls are added. User responses may be sensitive; do not copy them into public logs automatically.
