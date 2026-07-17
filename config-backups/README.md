# Restore Guide for Antigravity Configurations on a New Computer

This directory contains configuration files backed up from the global Antigravity settings on your old computer. When you switch to a new computer and sync the `UX Agent` directory via iCloud, follow these steps to restore your environment:

## Step 1: Initialize Antigravity on the New Computer
1. Ensure you have installed the latest version of Antigravity (CLI or IDE) on the new computer.
2. Launch the application or run the `agy` command in your terminal for the first time so the system automatically initializes the hidden `.gemini` home directory under `/Users/<new_username>/.gemini`.

## Step 2: Restore Configurations
1. Enable hidden files on macOS by pressing: `Cmd + Shift + .` (Command + Shift + Period).
2. Copy the files in this folder (`config.json` and `mcp_config.json`) and paste/overwrite them in the configuration directory of the new computer at:
   ```bash
   ~/.gemini/config/
   # (Equivalent to /Users/<new_username>/.gemini/config/)
   ```

> [!NOTE]
> * **Note on Permissions:** The backed-up `config.json` contains permission grants with absolute paths matching your old username (`/Users/madebynham/...`). On the new machine, the agent might prompt you to authorize file access again if your username changes. Simply click "Allow" to grant the new permission paths.
