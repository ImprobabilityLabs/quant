# Standard library imports
import os
import sys
import datetime

# Third-party imports
import requests
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort, current_app
from openai import OpenAI
import yfinance as yf
import pandas_ta as ta
import pandas as pd

from groq import Groq





def check_openai_key(api_key):
    """
    Checks the validity of the provided OpenAI API key by trying to list the available engines.

    Parameters:
    api_key (str): The OpenAI API key to validate.

    Returns:
    bool, str: Returns a tuple where the first element is a boolean indicating if the key is valid,
               and the second element is a message with details.
    """

    client = OpenAI(api_key=api_key)

    try:
        response = client.models.list()
        return True
    except Exception as e:
        return False


def get_stock_data(ticker, interval):
    """
    Downloads and calculates various technical indicators for stock data.

    Parameters:
    ticker (str): The stock ticker.
    interval (str): The interval of the stock data.

    Returns:
    tuple: A tuple containing:
           - DataFrame with the data or None if an error occurs,
           - a boolean indicating success,
           - an error message if applicable.
    """
    if interval == '1d':
        period = "1y"
        trim_len = 80
    elif interval == '1wk':
        period = '5y'
        trim_len = 80
    elif interval == '1mo':
        period = '10y'
        trim_len = 0
    else:
        current_app.logger.info(f'get_stock_data: error: Invalid interval specified.')
        return None, False, "Invalid interval specified."

    try:
        # Download historical data for the stock
        data = yf.download(ticker, period=period, interval=interval)
        if data.empty:
            return None, False, "No data found for the ticker."

        # Calculate ADX, RSI, Stochastic Oscillator, MACD, OBV, Aroon, CCI, Parabolic SAR, and Ichimoku Cloud
        data.ta.adx(append=True)
        data.ta.rsi(append=True)
        data.ta.stoch(append=True)
        data.ta.macd(append=True, histogram=True)
        data.ta.obv(append=True)
        data.ta.aroon(append=True)
        data.ta.cci(append=True)
        data.ta.psar(append=True)
        data.ta.ichimoku(append=True)

        # Round all numeric fields to two decimal places
        data = data.round(2)

        # Trim the first set of rows if applicable
        if len(data) > trim_len:
            data = data.iloc[trim_len:]

    except Exception as e:
        current_app.logger.info(f'get_stock_data: error: {str(e)}')
        return None, False, str(e)

    current_app.logger.info(f'get_stock_data: data: {str(data)}')
    return data, True, "Data successfully retrieved and processed."


def groq_cloud_anaysis(ticker, csv_data):
    """
    Requests a chat completion from GroqCloud's Llama 3.3 model to analyze stock data and identify trading opportunities.
    
    Parameters:
        ticker (str): The stock ticker symbol for which the analysis is requested.
        csv_data (str): The CSV data representing OHLCV values for the stock.
    
    Returns:
        str: The recommendation from the AI based on the analysis of the stock data.
    """
    # Define the system prompt for the analysis request
    system_prompt = (
        f"Analyze the provided OHLCV stock data for ticker {ticker} to uncover potential trading opportunities. "
        "If a favorable buying opportunity is identified for the upcoming period, reply with 'BUY', and provide a "
        "recommended Limit Sell price along with a Trailing Stop Loss (either in value or percentage). Conversely, if a "
        "selling opportunity for a short position is detected, reply with 'SELL', including a specific Limit Sell price "
        "and a Trailing Buy Stop Loss (either in price or percentage). If no definitive trading signal is found, respond "
        "with 'None'. Where possible explain the rationale, define the support and resistance  levels, and include a "
        "short bio of the ticker at the top of the response. Use the attached CSV file for performing the analysis:"
    )

    # Initialize the OpenAI client

    client = Groq()
    try:
        # Create a chat completion request using the system and user messages
        response = client.chat.completions.create(
          model="llama-3.3-70b-versatile",
          messages=[
            {
              "role": "system",
              "content": system_prompt
            },
            {
              "role": "user",
              "content": csv_data
            }
          ],
          temperature=1,
          top_p=1,
          stream=False,
          stop=None
        )

        # Return the final response text from the AI
        return completion.choices[0].message.content, None
    except Exception as e:
        return None, f"OpenAI Error! You probably don't have the model {model} available to your key. {str(e)}"




def open_ai_anaysis(api_key, model, ticker, csv_data):
    """
    Requests a chat completion from OpenAI's GPT model to analyze stock data and identify trading opportunities.
    
    Parameters:
        api_key (str): The API key for authenticating with OpenAI.
        model (str): The model identifier to use for the chat completion (e.g., "gpt-4o").
        ticker (str): The stock ticker symbol for which the analysis is requested.
        csv_data (str): The CSV data representing OHLCV values for the stock.
    
    Returns:
        str: The recommendation from the AI based on the analysis of the stock data.
    """
    # Define the system prompt for the analysis request
    system_prompt = (
        f"Analyze the provided OHLCV stock data for ticker {ticker} to uncover potential trading opportunities. "
        "If a favorable buying opportunity is identified for the upcoming period, reply with 'BUY', and provide a "
        "recommended Limit Sell price along with a Trailing Stop Loss (either in value or percentage). Conversely, if a "
        "selling opportunity for a short position is detected, reply with 'SELL', including a specific Limit Sell price "
        "and a Trailing Buy Stop Loss (either in price or percentage). If no definitive trading signal is found, respond "
        "with 'None'. Where possible explain the rationale, define the support and resistance  levels, and include a "
        "short bio of the ticker at the top of the response. Use the attached CSV file for performing the analysis:"
    )

    # Initialize the OpenAI client
    client = OpenAI(api_key=api_key)

    try:
        # Create a chat completion request using the system and user messages
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": csv_data
                }
            ],
            temperature=1,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )

        # Return the final response text from the AI
        return response.choices[0].message.content, None
    except Exception as e:
        return None, f"OpenAI Error! You probably don't have the model {model} available to your key. {str(e)}"
