# Sonar JaCoCo Analyzer

A Python tool for analyzing SonarCloud/SonarQube code quality issues and JaCoCo coverage reports.

## Features

- **Code Smell Analysis**: Analyzes code smell data from SonarCloud/SonarQube
- **Rule Mapping**: Maps issues to their corresponding quality rules
- **Technical Debt Calculation**: Tracks effort required and technical debt metrics
- **Severity Analysis**: Breaks down issues by severity levels
- **JaCoCo Coverage Analysis**: Analyzes JaCoCo HTML coverage reports
- **Structured Output**: Generates clean JSON output for integration with other tools

## Installation

### From Source (Development)

```bash
# Clone the repository
git clone https://github.com/username/sonar-jacoco-analyzer.git
cd sonar-jacoco-analyzer

# Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e .

# Or install with development dependencies
pip install -e ".[dev]"
```

### Using pip

```bash
pip install -r requirements.txt
```

## Usage

### Command Line Interface

After installation, you can use the `sonar-jacoco` command:

```bash
# Interactive mode (prompts for options)
sonar-jacoco

# Fetch data from SonarCloud API
sonar-jacoco --api

# Use local input.json file
sonar-jacoco --file

# Analyze JaCoCo coverage report
sonar-jacoco --jacoco path/to/report.zip

# Reset saved selections
sonar-jacoco --reset

# Show help
sonar-jacoco --help
```

### Running without Installation

```bash
python -m sonar_jacoco_analyzer.cli
```

## Configuration

### Environment Variables

Create a `.env` file based on `.env.example`:

```bash
cp .env.example .env
```

Required variables for API mode:
- `SONAR_TOKEN`: Your SonarCloud user token
- `SONAR_ORGANIZATION`: Your organization key

Optional:
- `SONAR_COOKIES`: Browser session cookies (alternative auth)
- `SONAR_XSRF_TOKEN`: XSRF token (required with cookies)

## Project Structure

```
sonar-jacoco-analyzer/
├── src/
│   └── sonar_jacoco_analyzer/
│       ├── __init__.py      # Package initialization
│       ├── api.py           # SonarCloud API client
│       ├── cli.py           # Command-line interface
│       └── jacoco.py        # JaCoCo report analyzer
├── tests/                   # Test files
├── .env.example             # Example environment configuration
├── .gitignore
├── pyproject.toml           # Modern Python packaging configuration
├── requirements.txt         # Runtime dependencies
├── requirements-dev.txt     # Development dependencies
└── README.md
```

## Output Format

The analyzer generates JSON output with:

```json
{
  "metadata": {
    "analysis_timestamp": "2025-09-20T12:00:00Z",
    "total_issues_analyzed": 18,
    "unique_rules_violated": 7,
    "total_technical_debt_minutes": 120
  },
  "issue_rule_mappings": [...],
  "rules_summary": [...],
  "severity_distribution": {...},
  "type_distribution": {...}
}
```

## Development

### Running Tests

```bash
pytest
```

### Code Formatting

```bash
black src/ tests/
ruff check src/ tests/
```

### Type Checking

```bash
mypy src/
```

## License

This project is open source. Please ensure compliance with your organization's security policies when handling SonarCloud data.
