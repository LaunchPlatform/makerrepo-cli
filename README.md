# makerrepo-cli

[![CircleCI](https://dl.circleci.com/status-badge/img/gh/LaunchPlatform/makerrepo-cli/tree/master.svg?style=svg)](https://dl.circleci.com/status-badge/redirect/gh/LaunchPlatform/makerrepo-cli/tree/master)

Command-line tool for manufacturing as code with or without [MakerRepo](https://makerrepo.com) account.
Build CAD models from code (e.g. Build123D), collect and work with artifacts locally, and run your full Manufacturing as Code workflow from your own machine—without depending on MakerRepo.com.

## Installation

Using [uv](https://docs.astral.sh/uv/):

```bash
# Install globally (recommended)
uv tool install makerrepo-cli
```

To add it to an existing project instead:

```bash
uv add makerrepo-cli
```

To run without installing (one-off or try-it runs):

```bash
uvx makerrepo-cli   # or: uvx mr
```

**CLI documentation:** [docs.makerrepo.com/makerrepo-cli](https://docs.makerrepo.com/makerrepo-cli/)
