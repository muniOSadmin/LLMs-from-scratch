# moswalk // Setup Guide
### For a new administrator with standard professional computer skills

This guide walks you through setting up and using the moswalk system
from scratch — no programming background required. Every step explains
what you're doing and why, not just what to type.

**Time to complete:** 30–45 minutes on a Mac with a good internet connection.

---

## Before you start: What is this system?

**moswalk** is a tool that helps anyone — an architect, an expediter, a property
owner, or a student — understand what New York City agencies are required for a
construction or renovation project, in what order, and why.

It has two parts:

```
moswalk-kernel     ← the open, free part. Anyone can use it.
                     Tells you: which agencies, in what sequence, what the law says.

pantocraft //      ← the professional part. For licensed architects/expediters.
                     Tells you: the fastest legal path, which professional tracks
                     to use, how to save weeks or months.
```

The system runs entirely on your own computer. Nothing is sent to a cloud.
No account required for the kernel.

---

## Part 1: The Tools You Need

### What is a "terminal"?

A terminal is a text-based window where you type commands directly to your
computer instead of clicking. It looks intimidating but follows simple rules:
you type a command, press Enter, and the computer responds.

**On a Mac:** Press `Command + Space`, type `Terminal`, press Enter.

A window opens with a blinking cursor. Everything you type here runs immediately
when you press Enter. You can't break anything by reading — only by running
commands. This guide will tell you exactly what to type.

---

### Step 1: Install Homebrew

**What it is:** Homebrew is a free tool that installs software on your Mac
the same way an app store installs apps — one command, no manual downloads.

**Open Terminal and paste this exactly:**

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Press Enter. It will ask for your Mac password (the one you use to log in).
Type it and press Enter — nothing shows on screen while you type, that's normal.

This takes 5–10 minutes. When it's done you'll see your cursor again.

**Verify it worked:**
```
brew --version
```
You should see something like: `Homebrew 4.x.x`

---

### Step 2: Install Python

**What it is:** Python is the programming language the system is written in.
Think of it as the engine. You don't need to understand Python to use it —
just like you don't need to understand gasoline to drive a car.

```
brew install python@3.11
```

**Verify it worked:**
```
python3 --version
```
You should see: `Python 3.11.x`

---

### Step 3: Install Git

**What it is:** Git tracks changes to files, like "Track Changes" in Word,
but for code. It also lets you download the moswalk code from the server.

```
brew install git
```

**Verify it worked:**
```
git --version
```
You should see: `git version 2.x.x`

---

### Step 4: Install PyYAML

**What it is:** A library that lets Python read `.yaml` files — the format
moswalk uses to store agency data and regulatory pathways.

```
pip3 install pyyaml
```

---

## Part 2: Get the Code

### Step 5: Choose where to keep the project

You need a folder on your computer to hold the moswalk code.
A clean, easy-to-find location is your home folder.

**In Terminal, type:**
```
cd ~
```
This moves you to your home directory (the same place your Desktop and
Documents folders live).

---

### Step 6: Download the code

**What this does:** "Cloning" downloads the entire project to your computer,
including all its history. The folder it creates is called `LLMs-from-scratch`.

```
git clone https://github.com/muniosadmin/llms-from-scratch.git
```

When it finishes:
```
cd LLMs-from-scratch
```

You are now inside the project folder. Every command from here on assumes
you are inside this folder. If you close Terminal and come back later,
you'll need to type `cd ~/LLMs-from-scratch` first.

---

### Step 7: Check out the working branch

The active development happens on a named branch. Think of a branch as
a version of the project — like "Draft v2" of a document.

```
git checkout claude/llm-iphone-17-pro-KuHhU
```

You should see: `Switched to branch 'claude/llm-iphone-17-pro-KuHhU'`

---

## Part 3: Verify Everything Works

### Step 8: Run the property trigger scanner smoke test

This test runs the core logic against three sample NYC properties
and shows what agencies and conditions are triggered.

**Type exactly:**
```
python3 moswalk-kernel/property/trigger_scanner.py
```

**You should see something like:**
```
SIM-001 conditions: ['Landmark building or within historic district', ...]
  blockers: ['LPC historic_district: Certificate of Appropriateness required...']

SIM-002 conditions: ['Flood zone AE or VE', 'Open ECB/DOB violations on record', ...]
  blockers: ['FLOOD ZONE AE: ADU pilot INELIGIBLE...']

SIM-006 conditions: [...]
  fisp_required: True
```

If you see these three blocks, the kernel is working correctly.

---

### Step 9: Look up what an agency does

The educational layer explains every agency in plain English.

**To look up the Department of Buildings:**
```
python3 moswalk-kernel/agencies/educational.py DOB
```

**To look up the Landmarks Preservation Commission:**
```
python3 moswalk-kernel/agencies/educational.py LPC
```

**To see a one-line summary of all agencies:**
```
python3 moswalk-kernel/agencies/educational.py
```

---

### Step 10: Resolve a pathway for a real project type

This is the core function — given a project type and property conditions,
what agencies are required?

**Type this exactly to open a Python session:**
```
python3
```

Your prompt changes to `>>>`. Now type these lines one at a time,
pressing Enter after each:

```python
import sys
sys.path.insert(0, 'moswalk-kernel')
from property.trigger_scanner import scan
from agencies.agency_navigator import AgencyNavigator
nav = AgencyNavigator()
```

**Now describe a property — a Brooklyn brownstone, 1895, in a historic district:**
```python
flags = scan({'landmarked': True, 'landmark_type': 'historic_district', 'year_built': 1895, 'stories': 3, 'zoning_district': 'R6B'})
result = nav.resolve('alteration_type_2', flags.conditions)
print(result.summary_table())
```

**You should see:**
```
STATUS   AGENCY         ROLE            DAYS BLOCKING   SEQ AFTER
------------------------------------------------------------------------
READY    LPC            approval          15 BLOCKING   —
READY    DOB            primary           45 BLOCKING   —
------------------------------------------------------------------------
Critical path: ~60 days  |  Total calendar: ~60 days
```

This means: LPC must approve before DOB can issue a permit. Critical path is
60 days. The law requires this sequence — it's not optional.

**To exit Python:**
```python
exit()
```

---

## Part 4: Understanding the File Structure

Here is what each folder is and whether you should edit it:

```
LLMs-from-scratch/
│
├── moswalk-kernel/            ← OPEN SOURCE — safe to read and edit
│   ├── compliance/
│   │   └── permit_pathways.yaml    ← the 8 pathway types and their agency sequences
│   ├── agencies/
│   │   ├── agency_navigator.py     ← the pathway resolver (don't edit unless told)
│   │   └── educational.py          ← plain English agency explanations (edit freely)
│   └── property/
│       └── trigger_scanner.py      ← property flags → agency conditions (don't edit)
│
├── pantocraft/                ← PROPRIETARY — handle carefully
│   ├── clients/               ← NEVER TOUCH — encrypted client data
│   ├── agentic/sessions/      ← NEVER COMMIT — private session logs
│   ├── intake/
│   │   └── client_intake.py   ← client engagement forms (licensed pros only)
│   ├── inference/
│   │   ├── edge_weights.yaml       ← professional optimization tracks (update carefully)
│   │   └── pathway_optimizer.py   ← applies tracks to pathways (don't edit)
│   └── field/
│       └── mobile_api.py           ← the iPhone field API (don't edit)
│
├── iphone-llm/                ← AI MODEL — advanced, don't edit unless trained
│   ├── agencies.yaml               ← 139 NYC agencies (OTI registry — update annually)
│   ├── sim/clients/                ← 8 simulated projects for testing
│   └── *.py                        ← model files (don't edit)
│
└── PANTOCRAFT.md              ← read this for the full vision
    SETUP.md                   ← this file
```

**The one file you will update most often:**
`moswalk-kernel/compliance/permit_pathways.yaml` — when NYC Local Laws change,
agency sequences change. Update this file to keep the system current.

**The one file you should never commit:**
Anything in `pantocraft/clients/`. These are encrypted client files.
The system prevents them from being uploaded automatically, but be aware.

---

## Part 5: Updating Agency Data

When a Local Law changes a filing requirement, or an agency gets a new portal,
you update the YAML files. YAML is not code — it's structured plain text.

### How to open and edit a YAML file

**In Terminal:**
```
open -a TextEdit moswalk-kernel/compliance/permit_pathways.yaml
```

This opens the file in TextEdit. You'll see the structure clearly:
agencies listed with their conditions, estimated days, and notes.

**Rules when editing YAML:**
- Indentation matters — use spaces, never tabs
- Quotes around values that contain colons or special characters
- Save with `Command + S`

**After editing, always test:**
```
python3 -c "import yaml; yaml.safe_load(open('moswalk-kernel/compliance/permit_pathways.yaml')); print('YAML OK')"
```

If you see `YAML OK`, your edit is valid. If you see an error, something
is misformatted — undo your last change (`Command + Z` in TextEdit) and try again.

---

### How to update an agency's estimated days

Example: DOB plan examination time changed from 90 to 75 days for NB filings.

1. Open `moswalk-kernel/compliance/permit_pathways.yaml` in TextEdit
2. Find the `new_building:` section
3. Find `code: "DOB"` under it
4. Change `typical_days: 90` to `typical_days: 75`
5. Save
6. Run the YAML test above

---

## Part 6: Saving Your Changes

When you've made updates you want to keep and share:

### Step 1: See what changed
```
git status
```
This shows which files you modified — green means new file, red means changed.

### Step 2: Stage your changes
```
git add moswalk-kernel/compliance/permit_pathways.yaml
```
Replace the filename with whatever file you changed.

### Step 3: Write a commit message
A commit message describes what you changed and why, in plain English.

```
git commit -m "Update DOB NB typical_days from 90 to 75 — DOB Q1 2026 processing time"
```

### Step 4: Upload to the server
```
git push
```

If it asks for a username and password, enter your GitHub credentials.

---

## Part 7: Getting Updates Others Made

When someone else updates the system and you want those updates on your computer:

```
git pull
```

This downloads and applies all recent changes. Always do this before starting
work to make sure you have the latest version.

---

## Part 8: Running the 8 Simulated Client Projects

The sim folder contains 8 fictional NYC projects that test the system.
You can run all of them at once to verify everything is working:

```
python3 iphone-llm/sim/sim_runner.py
```

You'll see the pathway resolved for each of the 8 clients:
Brooklyn rooftop, Queens ADU in a flood zone, Manhattan sidewalk café,
Bronx pre-1987 asbestos building, and more.

This is also a good way to understand how the system works —
read through the output and the YAML files in `iphone-llm/sim/clients/`
to see how each project's conditions map to agencies.

---

## Part 9: Common Problems and Solutions

**"command not found: python3"**
Python isn't installed or isn't on your PATH. Run `brew install python@3.11` again.

**"No module named yaml"**
Run: `pip3 install pyyaml`

**"FileNotFoundError: permit_pathways.yaml"**
You're not in the project folder. Run: `cd ~/LLMs-from-scratch` then try again.

**"error: pathspec ... did not match any file"** (when running git checkout)
The branch name was mistyped. Run `git branch -a` to see all available branches.

**The output looks wrong (missing LPC for a landmark property)**
Make sure you included `'landmarked': True` in your flags dict.
The scanner is exact — if the flag isn't there, the condition doesn't trigger.

**"Permission denied"**
Some pantocraft // files are locked (chmod 600). This is intentional —
they contain sensitive session data. You don't need to open them.

---

## Part 10: Privacy Rules (Important)

Three rules that must always be followed:

**1. Never commit client files.**
The `pantocraft/clients/` folder is gitignored — the system blocks it automatically.
But if you ever see a `.enc` file outside that folder, do not commit it.

**2. BBL is public. Client name is not.**
A BBL (Borough-Block-Lot, like `3-00783-0001`) is public record — fine to use
anywhere in the system. A client's name, contact info, or financial details
must only go in the encrypted client intake form, never in a YAML, never in a
commit message, never in a log file.

**3. If you're unsure, don't commit.**
Run `git status` and `git diff` to review everything before `git push`.
Once something is pushed to the server, it is in the history permanently.

---

## Quick Reference Card

Print this and keep it next to your computer.

```
Open Terminal on Mac:         Command + Space → type Terminal → Enter
Go to project folder:         cd ~/LLMs-from-scratch
Get latest updates:           git pull
Run agency smoke test:        python3 moswalk-kernel/property/trigger_scanner.py
Look up an agency:            python3 moswalk-kernel/agencies/educational.py DOB
Run all 8 sim clients:        python3 iphone-llm/sim/sim_runner.py
Check YAML syntax:            python3 -c "import yaml; yaml.safe_load(open('FILE.yaml'))"
See what you changed:         git status
Save changes to server:       git add FILE → git commit -m "message" → git push
```

---

*moswalk — Sovereign AI for NYC building professionals.*
*Information only. A licensed professional is always in the loop.*
