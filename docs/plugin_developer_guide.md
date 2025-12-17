# MAGI System Plugin Developer Guide

This guide describes how to develop plugins for the MAGI System, focusing on the new security features and architecture introduced in the System Hardening Refactor.

## Overview

MAGI plugins allow you to extend the system's capabilities by adding new commands, bridging to external tools, and customizing agent behaviors. The new plugin system enforces strict validation, asynchronous loading, and explicit permission management.

## Plugin Structure

Plugins are defined in YAML files. The structure is validated using Pydantic V2 schemas.

```yaml
plugin:
  name: "my-awesome-plugin"
  version: "1.0.0"
  description: "Adds awesome capabilities to MAGI"
  # signature or hash is required for loading
  signature: "..."

bridge:
  command: "python -m my_plugin"
  interface: "stdio"  # or "file"
  timeout: 30

# Optional: Requires explicit permission
agent_overrides:
  melchior: "Always consider quantum mechanical effects."
  balthasar: "Ensure compliance with Asimov's laws."
```

### Sections

- **plugin**: Metadata about the plugin.
  - `name` (required): Unique identifier.
  - `version`: SemVer string (default: "1.0.0").
  - `description`: Human-readable description.
  - `signature` (recommended): Base64 encoded signature (RSA-PSS or ECDSA).
  - `hash` (legacy): SHA256 digest of the canonicalized YAML.

- **bridge**: Configuration for the external process.
  - `command` (required): Shell command to execute.
  - `interface`: `stdio` (standard input/output) or `file` (file-based exchange).
  - `timeout`: Execution timeout in seconds (default: 30).

- **agent_overrides** (optional): Custom instructions appended to agent system prompts.
  - Keys: `melchior`, `balthasar`, `casper`.
  - Values: String containing the additional instructions.
  - **Note**: This feature is restricted by default. See "Permissions & Security".

## Permissions & Security

### Agent Overrides

Modifying agent prompts (`agent_overrides`) is a privileged operation because it can fundamentally alter the system's decision-making process.

**To enable `agent_overrides`:**

1.  **Global Configuration**: The user must enable overrides in `magi.yaml` or via environment variable.
    ```yaml
    # magi.yaml
    plugin_prompt_override_allowed: true
    ```
    Or `MAGI_PLUGIN_PROMPT_OVERRIDE_ALLOWED=true`.

2.  **Trust Requirement**: The plugin **MUST** be signed and explicitly trusted. Untrusted plugins cannot use overrides even if the global setting is enabled.
    *   The plugin must have a valid `signature`.
    *   The signature must be listed in `plugin_trusted_signatures`.

### Signing a Plugin

To sign a plugin, you need a private key (RSA or ECDSA). The MAGI System verifies signatures using the corresponding public key.

#### 1. Generate Keys (Example using OpenSSL)

```bash
# Generate Private Key (keep this safe!)
openssl genpkey -algorithm RSA -out private_key.pem -pkeyopt rsa_keygen_bits:2048

# Extract Public Key (distribute this or configure in MAGI)
openssl rsa -pubout -in private_key.pem -out public_key.pem
```

#### 2. Canonicalize the YAML

Before signing, the YAML content must be "canonicalized" to ensure consistency.
The canonicalization process:
1.  Parses the YAML.
2.  Removes the `plugin.signature` field (to avoid self-reference).
3.  Dumps it back to YAML using `sort_keys=True` and `allow_unicode=True`.
4.  Normalizes line endings to `\n` (LF) and strips leading/trailing whitespace.
5.  Encodes to UTF-8 bytes.

#### 3. Generate Signature

You can use the `magi` CLI (if available) or a script to sign.
Since the canonicalization logic is specific, it is recommended to use a Python script importing `PluginSignatureValidator`.

**Example Signing Script:**

```python
import sys
import base64
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from magi.plugins.signature import PluginSignatureValidator

def sign_plugin(yaml_path, private_key_path):
    # 1. Read YAML
    content = Path(yaml_path).read_text(encoding="utf-8")
    
    # 2. Canonicalize
    payload = PluginSignatureValidator.canonicalize(content)
    
    # 3. Load Private Key
    with open(private_key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(
            f.read(),
            password=None
        )
    
    # 4. Sign (RSA-PSS SHA256)
    signature = private_key.sign(
        payload,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    
    # 5. Encode
    sig_b64 = base64.b64encode(signature).decode("utf-8")
    print(f"Signature for {yaml_path}:")
    print(sig_b64)

if __name__ == "__main__":
    sign_plugin(sys.argv[1], sys.argv[2])
```

#### 4. Add Signature to YAML

Copy the generated Base64 string into your plugin YAML:

```yaml
plugin:
  name: "my-plugin"
  # ...
  signature: "<YOUR_BASE64_SIGNATURE>"
```

### Registering a Trusted Plugin

For users to trust your plugin (and allow overrides):

1.  **Deploy Public Key**: The user must point `MAGI_PLUGIN_PUBKEY_PATH` to your public key (or the public key used to sign their trusted plugins).
    *   *Note*: Currently MAGI supports a single public key path for verification.

2.  **Allow Signature**: The user must add the specific plugin's signature to their trusted list.

```yaml
# magi.yaml
plugin_trusted_signatures:
  - "<YOUR_BASE64_SIGNATURE>"
```

## Best Practices

-   **Async Compatibility**: Plugins are loaded asynchronously. Ensure your initialization doesn't block significantly.
-   **Error Handling**: If your bridge command fails or times out, the plugin will be isolated. Design your plugin to fail gracefully.
-   **Production Mode**: In `production_mode=True`, the system will **NOT** search for `plugins/public_key.pem` in the current directory. You must explicitly configure the public key path.