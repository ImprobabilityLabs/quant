# Quant by Improbability Labs

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/Flask-2.0%2B-green)](https://flask.palletsprojects.com/)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4-orange)](https://openai.com/)

Quant is an AI-powered stock analysis tool developed by [Improbability Labs Inc.](https://improbability.io/). It leverages your own OpenAI API key to provide personalized and advanced technical analysis based on OHLCV (Open, High, Low, Close, Volume) data.

Access the live application at **[quant.improbability.io](https://quant.improbability.io/)**.

## Table of Contents

- [Features](#features)
- [Demo](#demo)
- [Installation](#installation)
- [Usage](#usage)
- [Requirements](#requirements)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

## Features

- **AI-Driven Analysis**: Utilizes OpenAI's GPT models to analyze stock data and provide trading recommendations.
- **Technical Indicators**: Calculates various technical indicators including ADX, RSI, MACD, OBV, Aroon, CCI, Parabolic SAR, and Ichimoku Cloud.
- **Customizable Inputs**: Users can input their own OpenAI API key, select the AI model, stock ticker, and time period for analysis.
- **Web Interface**: Built with Flask, providing an easy-to-use web interface for users.
- **Secure and Private**: Your OpenAI API key is not stored on the server; all processing is done securely.

## Demo

Visit the live application: [quant.improbability.io](https://quant.improbability.io/)

![Quant Screenshot](https://your-image-url.com/screenshot.png) <!-- Replace with actual screenshot URL -->

## Installation

### Prerequisites

- Python 3.8 or higher
- OpenAI API Key (You can get one from [OpenAI](https://openai.com/))
- SendGrid API Key (Optional, for email functionalities)
- Git

### Clone the Repository

```bash
git clone https://github.com/ImprobabilityLabs/quant.git
cd quant
```

### Create a Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Environment Variables

Create a .env file in the root directory and add the following:
```env
LOG_PATH=/var/log/improbability/quant/
SECRET_KEY=your_secret_key
SENDGRID_API_KEY=your_sendgrid_api_key
GOOGLE_ANALYTICS_ID=your_google_analytics_id
GOOGLE_SITE_VERIFICATION=your_google_site_verification
BING_SITE_VERIFICATION=your_bing_site_verification
```

### Run the Application
```bash
flask run
```

The application will be available at http://localhost:5000.

## Usage
1. Open the application in your web browser.
2. Enter your OpenAI API key.
3. Select the AI model (e.g., gpt-4).
4. Input the stock ticker symbol (e.g., AAPL for Apple Inc.).
5. Choose the stock period (1d, 1wk, or 1mo).
6. Click Submit to receive the AI-generated analysis.

## Python Requirements
*Python Packages:*
- Flask
- yfinance
- pandas
- pandas_ta
- openai
- requests
- gunicorn

## System Services:
- Nginx (for serving the application)
- Systemd (for managing the application service)
- CertBot ( for free SSL certs )

## Contributing
We welcome contributions! Please follow these steps:

- Fork the repository.
- Create a new branch for your feature or bugfix.
- Commit your changes with clear messages.
- Submit a pull request to the main branch.

## License
This project is licensed under the Apache License 2.0.

## Contact
*Website:* improbability.io

*Email:* support@improbability.io

*Improbability Labs LinkedIn:* https://www.linkedin.com/company/improbability-labs/

*Rahim's LinkedIn:* https://www.linkedin.com/in/rahim-khoja-879944139/

Developed by Improbability Labs Inc. [Rahim Khoja](mailto:rahim@khoja.ca)
