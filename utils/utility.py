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

    if interval == '1d':
        period = "1y"
        trim_len = 80
    elif interval == '1wk':
        period = '5y'
        trim_len = 80
    elif interval == '1mo':
        period = '10y'
        trim_len = 0

    # Download historical data for the stock
    data = yf.download(ticker, period=period, interval=interval)

    # Check if the data is empty
    if data.empty:
        print("No data found for the ticker.")
        return False

    # Calculate ADX, MACD, RSI, and Bollinger Bands
    data.ta.adx(append=True)
    #data.ta.macd(append=True)
    data.ta.rsi(append=True)

    # Adding Stochastic Oscillator
    data.ta.stoch(append=True)

    # Adding MACD Histogram
    data.ta.macd(append=True, histogram=True)

    # Adding On-Balance Volume
    data.ta.obv(append=True)

    # Adding Aroon Indicator
    data.ta.aroon(append=True)

    # Adding Commodity Channel Index
    data.ta.cci(append=True)

    # Adding Parabolic SAR
    data.ta.psar(append=True)

    # Adding Ichimoku Cloud
    data.ta.ichimoku(append=True)


    # Round all numeric fields to two decimal places
    data = data.round(2)

    # Trim the first 80 rows
    if len(data) > trim_len:
        data = data.iloc[trim_len:]
    else:
        print(f"The dataset contains less than {str(trim_len)} rows. No rows will be trimmed.")
        return False

    # Print the data with indicators
    return(data, ticker)

