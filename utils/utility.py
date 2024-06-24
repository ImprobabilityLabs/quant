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
        return None, False, str(e)

    return data, True, "Data successfully retrieved and processed."


