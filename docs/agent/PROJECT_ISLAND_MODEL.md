# Project Island Operating Model

## Core Idea

An agent-prepared project is normally an island-like function block. The human supplies a briefing, task, project documentation, reference material, and other inputs. The agent processes those inputs and produces source code, documentation, reports, logs, resources, and other outputs inside the declared project working directory.

The concise rule is:

> The agent should see the world around it and communicate with it, but only modify within its own working directory.

The working directory is a default mutation boundary, not an observation boundary and not an offline mode. A current human request may explicitly authorize a narrow exception.

## Expected Inputs and Outputs

Typical inputs include:

- the current human task or project proposal;
- root `AGENTS.md`, the compiled `agent/` guidance, and the project briefing;
- project source, documentation, resources, datasets, and local references;
- information read from the wider computer, internet, connected devices, or authorized services.

Typical outputs remain within the project:

- implementation and configuration files;
- project-local dependency environments and generated artifacts;
- reports and compiled considerations in `docs/`;
- raw captures in `logs/`;
- mutable runtime state in `data/`;
- temporary material in `tmp/`.

## Observation and Communication Are Allowed

When relevant to the task and otherwise safe, the island boundary does not prohibit:

- internet research;
- downloading public or authorized input data into the project;
- read access to other locations on the computer or system;
- discovering and executing already installed system or user-level tools and toolchains, including compilers, SDKs, interpreters, debuggers, and command-line utilities;
- reading from connected microcontrollers, smartphones, cameras, storage media, and other peripherals;
- task-scoped interaction with peripherals, including flashing firmware or deploying an application when the task authorizes that device operation;
- outgoing network traffic needed by the project;
- sending text status messages, results, or questions through an approved communication channel.

These capabilities do not authorize unrelated exploration, disclosure of secrets, unsafe hardware operations, or bypassing a system permission boundary. Existing task scope, privacy rules, credential handling, and human-approval requirements still apply.

## Mutations Outside the Island Require Approval

Unless the human explicitly requests or approves the exact exception, an agent must not:

- install packages into a global or user-level Python interpreter;
- install system-wide software, operating-system packages, drivers, services, or privileged components;
- modify another project, checkout, or directory outside the declared working directory;
- upload project files, evidence, source, datasets, or archives to cloud storage, source hosting, permanent public archives, Software Heritage, or similar services;
- push commits, tags, branches, releases, or other changes to a remote Git host;
- create, update, or delete records in a database hosted outside the project;
- perform another persistent external mutation merely because read or network access is available.

Project-local dependencies are allowed when the task needs them and they remain inside the working directory, such as `scripts/.venv`, a local package cache, or a normal project dependency tree covered by the project's conventions. An existing system or user-level Python interpreter may run `-m venv` to create `scripts/.venv`; this reads and executes the installed toolchain while keeping the new environment and dependency mutations inside the project. It does not authorize installing packages into that bootstrap interpreter.

Sending a text message is an explicit communication exception to the external-mutation rule. It does not imply permission to attach or upload project files, create unrelated service records, or disclose credentials or private data.

## Approval for an Exception

An exception must come from a current explicit human request or approval. Before asking, the agent should state:

- the exact external target;
- the intended change and why it is necessary;
- the data or credentials involved;
- expected side effects and persistence;
- the narrower alternatives considered;
- how the change can be verified or recovered.

Approval is narrow. Permission to deploy an app to one connected phone does not authorize installing a driver, changing another project, uploading files, or mutating a remote database. Permission to send a status message does not authorize sending attachments.

## Repository Consequences

Projects should contain enough briefing, documentation, references, data, and tools to make outside project discovery exceptional. Their root `brief.md` must declare the workspace root, primary implementation target, local inputs, and any intentionally authorized external target.

The model favors reproducible handoffs: the same documented inputs should let an agent produce reviewable project-local outputs without depending on hidden global state or silently modifying the surrounding machine.
