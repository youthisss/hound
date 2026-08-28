# Contributing to Hound Agent

Thank you for your interest in contributing to Hound Agent! We welcome contributions from the community.

## Code of Conduct

Please be respectful, constructive, and collaborative in all communications and reviews.

## Getting Started

### Prerequisites
- Python >= 3.10
- [`uv`](https://docs.astral.sh/uv/) (recommended package and project manager)
- Git

### Development Setup

1. Fork and clone the repository:
   ```sh
   git clone https://github.com/youthisss/hound-agent.git
   cd hound-agent
   ```

2. Create virtual environment and install dev dependencies:
   ```sh
   uv sync --extra dev
   ```

3. Verify test suite passes:
   ```sh
   uv run pytest
   ```

## Development Workflow

1. **Create a branch**:
   ```sh
   git checkout -b feat/your-feature-name
   ```

2. **Code Guidelines**:
   - Write clean, type-annotated Python.
   - All diagnostic tools must be deterministic and privacy-first (redaction enabled by default).
   - Machine-readable stdout (`--format json`) must never be polluted by logs.
   - Do not commit secrets, API keys, or private log samples.

3. **Verify Quality Gates**:
   Before submitting a pull request, ensure all checks pass:
   ```sh
   uv run ruff check .
   uv run mypy hound_agent
   uv run pytest --cov=hound_agent --cov-report=term --cov-fail-under=80 -q
   ```

4. **Submit a Pull Request**:
   - Use [Conventional Commits](https://www.conventionalcommits.org/) format for commit messages (e.g., `feat:`, `fix:`, `docs:`, `test:`).
   - Describe the problem solved and include reproduction steps or fixture evidence where applicable.
