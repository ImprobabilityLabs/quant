# Standard library imports
import json
import os
import re
import sys
import time
import asyncio
from datetime import datetime

# Third-party imports
import requests
import stripe
import phonenumbers
import secrets
import aiohttp
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort, current_app
from flask_sqlalchemy import SQLAlchemy
from twilio.rest import Client
from twilio.request_validator import RequestValidator
from oauthlib.oauth2 import WebApplicationClient
from requests_oauthlib import OAuth2Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from phonenumbers.phonenumberutil import region_code_for_number
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from regex import regex
from groq import Groq
from openai import OpenAI

# Local application/library specific imports
from models import db, User, Subscription, MobileNumber, History, UserPreference, AssistantPreference 

async def answer_question(question, user_input):
    """
    Asynchronously fetches an answer to a question using the Groq API.

    Args:
        question (str): The question to answer.
        user_input (str): Additional context or prompt for the AI.

    Returns:
        str: The AI-generated answer or None if an error occurs.
    """
    # Log the input question for debugging purposes
    current_app.logger.debug(f"Received question: {question}")

    try:
        # API endpoint for Groq AI completions
        api_url = "https://api.groq.com/openai/v1/chat/completions"
        
        # Headers including authorization and content type
        headers = {
            "Authorization": f"Bearer {current_app.config['GROQ_KEY']}",
            "Content-Type": "application/json"
        }
        
        # Payload to send, including model details and messages
        payload = {
            "model": "llama3-70b-8192",
            "messages": [
                {
                    "role": "system",
                    "content": f"Extract the answer to '{question}', and output it in a paragraph with any additional relevant information. Try and convert any company name to their stock symbols in the outputted questions."
                },
                {
                    "role": "user",
                    "content": user_input
                }
            ],
            "temperature": 1,
            "max_tokens": 386,
            "top_p": 1,
            "stream": False,
            "stop": None
        }

        # Asynchronous HTTP session
        async with aiohttp.ClientSession() as session:
            # POST request with timeout
            async with session.post(api_url, headers=headers, json=payload, timeout=10) as response:
                response.raise_for_status()  # Raises an HTTPError for bad responses
                response_json = await response.json()
                # Log the response for debugging
                current_app.logger.debug(f"API Response: {response_json}")
                # Extract the answer from the response
                return response_json['choices'][0]['message']['content']
    except Exception as e:
        # Log any exceptions that occur during the function execution
        current_app.logger.error(f"An error occurred while answering the question: {e}")
        return None

async def fetch_data(question, location=None):
    """
    Fetch data from the DataForSEO API for the specified question.
    
    Args:
    - question (str): The search query or question.
    - location (str, optional): The geographical location code (default=None, which sets to US).
    
    Returns:
    - dict or None: The result from the DataForSEO API or None if an error occurs.
    """
    # API endpoint
    url = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
    current_app.logger.debug(f"fetch_data() called with question: {question}, location: {location}")
    
    # Determine the location code based on input, default is US (2840)
    location_code = 2840 if location not in ['US', 'CA'] else (2124 if location == 'CA' else 2840)
    
    # Construct the request payload
    payload = json.dumps([{
        "keyword": question,
        "location_code": location_code,
        "language_code": "en",
        "device": "desktop",
        "os": "windows",
        "depth": 1
    }])
    
    # Headers for the API request
    headers = {
        'Authorization': f"Basic {current_app.config['SEO_FOR_DATA_KEY']}",
        'Content-Type': 'application/json'
    }

    # Perform the HTTP POST request asynchronously
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, data=payload, timeout=10) as response:
                current_app.logger.debug(f"HTTP POST response status: {response.status}")
                response.raise_for_status()  # Ensure we notice bad responses
                response_text = await response.text()
                current_app.logger.debug(f"HTTP response text: {response_text}")
                data = await response.json()
                current_app.logger.debug(f"Response JSON: {data}")

                # Check if expected data is in the response
                if 'tasks' in data and data['tasks'] and 'result' in data['tasks'][0]:
                    return data['tasks'][0]['result']
                else:
                    current_app.logger.warning("No result found in response")
                    return None

        except aiohttp.ClientError as e:
            current_app.logger.error(f"Request failed due to client error: {e}")
            return None
        except json.JSONDecodeError:
            current_app.logger.error("Failed to decode JSON response")
            return None
        except KeyError:
            current_app.logger.error("Unexpected response structure")
            return None

async def process_questions_answers(text_message, location, location_country='US'):
    """
    Process text messages to extract questions and fetch answers based on the given location and country.
    
    Args:
        text_message (str): The message text containing questions.
        location (str): Location information used in data fetching.
        location_country (str, optional): Country information used in data fetching. Defaults to 'US'.
    
    Returns:
        list or None: A list of answers if available, None otherwise.
    """
    try:
        # Trim whitespace from the text message for clean processing
        text_message = text_message.strip()

        # Log the processing step
        current_app.logger.debug("Starting to process the text message.")

        # Check if text_message is empty after stripping
        if not text_message:
            current_app.logger.error("Empty text message received.")
            return None

        # Extract questions from the text message
        questions = extract_questions(text_message, location)
        current_app.logger.debug(f"Extracted questions: {questions}")

        # List to hold the answers
        answers = []

        # Process each question to fetch and clean data
        for question in questions:
            current_app.logger.debug(f"Processing question: {question}")

            # Fetch data based on the question and location country
            fetched_answer = await fetch_data(question, location_country)
            if fetched_answer is None:
                current_app.logger.warning(f"No answer fetched for question: {question}")
                continue

            # Clean the fetched data
            cleaned_answer = clean_data(fetched_answer)

            # Generate the final answer from the question and cleaned data
            answer = await answer_question(question, cleaned_answer)
            current_app.logger.debug(f"Final answer for '{question}': {answer}")
            
            # Add the processed answer to the list
            answers.append(answer)

        # Return the list of processed answers
        return answers

    except Exception as e:
        # Log any exceptions that occur during the process
        current_app.logger.error(f"Error in process_questions_answers: {e}")
        return None

def extract_questions(message_text, location_text):
    """
    Extracts and reformats questions from a given text using an AI model.
    
    Args:
    message_text (str): The text from which questions are to be extracted.
    location_text (str): Location description to be included in questions where needed.
    
    Returns:
    list: A list of cleaned and reformatted questions.
    """
    current_app.logger.debug("Starting the extraction of questions.")
    
    try:
        # Validate the message_text input to ensure it's a string
        if not isinstance(message_text, str):
            raise ValueError("message_text must be a string")
        
        # Prepare the system message for the AI model
        system_message = (
            "Extract questions from the text. Reframe each question to make it standalone and understandable "
            "without additional context. Output each question on a separate line with a question mark. "
            "Only output questions. Ignore questions related to personal or specific context that cannot be "
            "understood or answered without additional private knowledge. Do not include Notes or extra information. "
            "If no questions are found, reply without a question mark. If a question's location is ambiguous or unknown, "
            f"incorporate the provided location into the question text: '{location_text}'."
        )

        # Log the prepared system message
        current_app.logger.debug("System message prepared for AI model.")

        # Initialize the AI model client and request question extraction
        client = Groq()
        completion = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": json.dumps(message_text)}
            ],
            temperature=1,
            max_tokens=386,
            top_p=1,
            stream=False,
            stop=None,
        )

        # Log the token usage information
        current_app.logger.info(f"Tokens used: {completion.usage}")

        # Process the AI's response to integrate the location text
        lines = completion.choices[0].message.content.split('\n')
        for phrase in ["near me", "to me?", "current location", "where I am located"]:
            lines = [line.replace(phrase, 'near ' + location_text) for line in lines]
        
        # Log the processed lines
        current_app.logger.debug("Questions processed with location context.")

        # Filter and clean the questions
        filtered_questions = [re.sub(r"[^\w\s?.-]", "", line).strip() for line in lines if '?' in line]

        # Log the filtered questions
        current_app.logger.debug(f"Filtered questions: {filtered_questions}")

        return filtered_questions

    except Exception as e:
        # Log error details
        current_app.logger.error(f"An error occurred: {str(e)}")
        return []

def remove_keys(data, keys_to_remove):
    """
    Recursively remove specified keys from a dictionary or list of dictionaries.

    Args:
    data (dict or list): The input data from which keys need to be removed.
    keys_to_remove (list): A list of keys that need to be removed from the data.

    Returns:
    dict or list: The modified data with specified keys removed.
    """
    if isinstance(data, dict):
        # Iterate over each key-value pair in the dictionary and apply the function recursively
        current_app.logger.debug(f"Processing a dictionary with keys: {data.keys()}")
        modified_dict = {key: remove_keys(value, keys_to_remove)
                         for key, value in data.items() if key not in keys_to_remove}
        return modified_dict
    elif isinstance(data, list):
        # Apply the function to each item in the list recursively
        current_app.logger.debug("Processing a list of items")
        modified_list = [remove_keys(item, keys_to_remove) for item in data]
        return modified_list
    else:
        # Return the item unchanged if it is neither a dictionary nor a list
        current_app.logger.debug("Encountered a non-list, non-dict type; returning it unchanged")
        return data

def clean_data(data):
    """
    Removes unnecessary keys from the data and returns the cleaned data in JSON format.
    
    Args:
        data (dict): The original dictionary from which unnecessary keys will be removed.

    Returns:
        str: A JSON string of the cleaned dictionary with a readable indentation.

    The function uses a predefined set of keys that are considered unnecessary for further processing and should be removed.
    """
    # Define a set of keys that need to be removed from the input data
    keys_to_remove = {
        'xpath', 'image_url', 'url', 'images', 'cache_url', 'is_image', 'is_video', 'type',
        'rank_group', 'rank_absolute', 'position', 'rectangle', 'reviews_count', 'rating',
        'place_id', 'feature', 'cid', 'data_attrid', 'domain', 'faq', 'extended_people_also_search',
        'about_this_result', 'timestamp', 'related_result', 'se_domain', 'location_code',
        'language_code', 'check_url', 'datetime', 'se_results_count', 'items_count', 'related_search_url',
        'breadcrumb', 'is_malicious', 'is_web_story', 'amp_version', 'card_id', 'logo_url',
        'is_featured_snippet', 'pre_snippet', 'extended_snippet', 'price', 'links'
    }

    # Log the initial state of data for debugging purposes
    current_app.logger.debug("Starting data cleanup process.")

    # Removing the keys from the data
    cleaned_data = remove_keys(data, keys_to_remove)

    # Convert the cleaned dictionary to a JSON string with indentation for readability
    cleaned_json = json.dumps(cleaned_data, indent=2)

    # Log the completion of the data cleanup process
    current_app.logger.info("Data cleanup completed successfully.")

    return cleaned_json

def sanitize_string(input_string, max_length):
    """
    Sanitizes the input string by trimming whitespace and cutting it to a maximum specified length.
    
    Args:
    input_string (str): The string to sanitize.
    max_length (int): The maximum allowable length of the string after sanitization.
    
    Returns:
    str: The sanitized string.
    
    Logs:
    Debug: Logs the original and the sanitized string values.
    """
    # Convert the input to a string (in case it isn't) and trim whitespace
    trimmed_string = str(input_string).strip()
    
    # Limit the string to the specified maximum length
    limited_length_string = trimmed_string[:max_length]
    
    # Log the original and sanitized values for debugging
    current_app.logger.debug(f"Original: {input_string}, Sanitized: {limited_length_string}")
    
    return limited_length_string

def format_phone_number(phone_number):
    """
    Format a given phone number into a more readable format.

    This function assumes that the input phone number is in the format +1XXXXXXXXXX
    (where '1' stands for the US country code and 'XXXXXXXXXX' represents the 10-digit phone number).
    It reformats the phone number to the style +1 (XXX) XXX-XXXX.

    Parameters:
        phone_number (str): The phone number to format.

    Returns:
        str: The formatted phone number.
    """
    try:
        # Log the original phone number
        current_app.logger.debug(f"Original phone number received: {phone_number}")

        # Ensure the phone number starts with +1 and is exactly 12 characters long
        if not phone_number.startswith('+1') or len(phone_number) != 12:
            current_app.logger.error("Invalid phone number format.")
            return phone_number  # Return the original input if it doesn't meet the criteria

        # Slice the phone number to create the formatted string
        formatted_number = f"+1 ({phone_number[2:5]}) {phone_number[5:8]}-{phone_number[8:]}"

        # Log the formatted phone number
        current_app.logger.info(f"Formatted phone number: {formatted_number}")
        
        return formatted_number
    except Exception as e:
        # Log any exceptions that occur during the formatting
        current_app.logger.error(f"Error formatting phone number: {e}")
        return phone_number  # Return the original input in case of error

def clean_string(input_string):
    """
    Cleans the input string by removing emoji and similar characters, 
    but retains characters used in major languages.
    
    Args:
    input_string (str): The string to be cleaned.

    Returns:
    str: The cleaned string.
    """
    # Logging the input string for debugging
    current_app.logger.debug("Starting to clean the string: %s", input_string)
    
    # Define a regex pattern to match emoji and symbols
    emoji_pattern = regex.compile(
        '['
        '\p{Cs}'  # Surrogate codes
        '\p{Sk}'  # Symbol, modifier
        '\p{So}'  # Symbol, other
        '\p{Cn}'  # Unassigned
        ']+', 
        flags=regex.UNICODE
    )

    # Remove matched patterns from the string
    cleaned_string = emoji_pattern.sub('', input_string)

    # Logging the cleaned string for debugging
    current_app.logger.debug("Finished cleaning the string: %s", cleaned_string)
    
    return cleaned_string

def check_user_subscription(provider_id):
    """
    Check the subscription status of a user based on their provider ID.

    Args:
    provider_id (str): The unique identifier for the user from an external provider.

    Returns:
    dict: A dictionary containing boolean status of user existence, subscription status, and billing error presence.
    """
    # Initialize the result dictionary to store user status
    user_status = {
        "is_user": False,
        "is_subscribed": False,
        "has_billing_error": False
    }
    
    # Log the attempt to find the user
    current_app.logger.debug(f"Attempting to find user with provider ID: {provider_id}")
    
    # Query the user based on provider_id
    user = User.query.filter_by(provider_id=provider_id).first()
    
    # Check if the user exists
    if user:
        current_app.logger.info(f"User found: {user.id}")
        user_status['is_user'] = True
        
        # Query the subscription based on user id and check if it is enabled
        subscription = Subscription.query.filter_by(user_id=user.id, enabled=True).first()
        
        if subscription:
            current_app.logger.info(f"Active subscription found for user ID: {user.id}")
            user_status['is_subscribed'] = True
            
            # Check if there is a billing error
            if subscription.billing_error:
                current_app.logger.error(f"Billing error found for user ID: {user.id}")
                user_status['has_billing_error'] = True
        else:
            current_app.logger.warning(f"No active subscription found for user ID: {user.id}")
    else:
        current_app.logger.warning(f"No user found with provider ID: {provider_id}")
    
    return user_status

def generate_menu(member):
    """
    Generates navigation menu items based on the member's status.
    
    Args:
    - member (dict): A dictionary containing member's subscription and user status.
    
    Returns:
    - list: A list of dictionaries where each dictionary represents a menu item.
    """
    # Initialize the menu list
    menu = []

    # Check if the member is not a user
    if not member['is_user']: 
        current_app.logger.debug("Generating menu for non-user.")
        menu = [
            {"name": "Home", "url": "/"},
            {"name": "About", "url": "/about"},
            {"name": "FAQ", "url": "/faq"},
            {"name": "Contact", "url": "/contact"},
        ]

    # Check if the member is a user but not subscribed
    elif member['is_user'] and not member['is_subscribed']:
        current_app.logger.debug("Generating menu for unsubscribed user.")
        menu = [
            {"name": "Home", "url": "/"},
            {"name": "Subscribe", "url": "/subscribe"},
            {"name": "Contact", "url": "/contact"},
            {"name": "Logout", "url": "/logout"},
        ]

    # Check if the member is a subscribed user without billing errors
    elif member['is_user'] and member['is_subscribed'] and not member['has_billing_error']:
        current_app.logger.debug("Generating menu for subscribed user without billing issues.")
        menu = [
            {"name": "Home", "url": "/"},
            {"name": "Dashboard", "url": "/dashboard"},
            {"name": "Account", "url": "/account"},
            {"name": "Logout", "url": "/logout"},
        ]

    # Check if the member is a subscribed user with billing errors
    elif member['is_user'] and member['is_subscribed'] and member['has_billing_error']:
        current_app.logger.warning("Generating menu for subscribed user with billing issues.")
        menu = [
            {"name": "Home", "url": "/"},
            {"name": "Account", "url": "/account"},
            {"name": "Contact", "url": "/contact"},
            {"name": "Logout", "url": "/logout"},
        ]

    # Return the generated menu
    return menu

def get_products():
    """
    Retrieves a list of product details including associated prices and metadata from Stripe.

    Returns:
        list: A list of dictionaries, each containing details about a product.
    """
    # Fetch a list of products from Stripe with a specified limit
    try:
        products = stripe.Product.list(limit=10, active=True)
        current_app.logger.info("Successfully retrieved products from Stripe.")
    except Exception as e:
        current_app.logger.error(f"Error fetching products from Stripe: {e}")
        return []  # Return an empty list in case of failure

    product_data = []

    # Iterate through each product retrieved from Stripe
    for product in products.auto_paging_iter():
        current_app.logger.debug(f"Processing product {product.id}")

        # Fetch recurring prices for each product
        try:
            prices = stripe.Price.list(product=product.id, type='recurring', active=True)
            current_app.logger.debug(f"Retrieved prices for product {product.id}")
        except Exception as e:
            current_app.logger.error(f"Error fetching prices for product {product.id}: {e}")
            continue  # Skip to the next product on error

        # Iterate through each price object retrieved
        for price in prices.data:
            # Calculate and format amount
            amount = price.unit_amount / 100
            formatted_amount = f"{amount:.2f}"

            # Retrieve and format product and pricing details
            description = product.description or ""
            country = product.metadata.get('country', '')
            tax_rate = float(product.metadata.get('tax', 0.0))
            tax_name = product.metadata.get('tax_name', '')
            long_description = product.metadata.get('long_desc', '')
            features = [feature['name'] for feature in product.get('marketing_features', [])]

            # Handle product images, providing a default if none are available
            images = product.images
            image_url = images[0] if images else 'https://example.com/default-image.jpg'

            # Append the detailed product data to the list
            product_data.append({
                'product_id': product.id,
                'price_id': price.id,
                'amount': formatted_amount,
                'currency': price.currency.upper(),
                'interval': price.recurring.interval,
                'description': description,
                'country': country,
                'features': features,
                'image_url': image_url,
                'product_name': product.name,
                'long_desc': long_description
            })

    current_app.logger.info("Completed processing all products.")
    return product_data

def update_customer_billing_info(user, form_data):
    """
    Updates the billing information of a customer in Stripe based on the provided form data.
    
    Parameters:
    - user: The user object containing user-specific data like email and stripe_customer_id.
    - form_data: A dictionary containing the billing information fields from a submitted form.
    
    Returns:
    - True if the billing information was successfully updated, False otherwise.
    """
    
    # Log the initiation of the billing info update process
    current_app.logger.info("Starting update of customer billing information for user ID %s.", user.id)
    
    try:
        # Sanitize and assign the card name from form data
        sanitized_card_name = sanitize_string(form_data['card-name'], 30)
        
        # Retrieve the existing customer from Stripe
        customer = stripe.Customer.retrieve(user.stripe_customer_id)
        current_app.logger.debug("Retrieved Stripe customer data for user ID %s.", user.id)
        
        # Update customer details in Stripe
        customer.name = sanitized_card_name
        customer.email = user.email
        customer.address = {
            'line1': sanitize_string(form_data['billing-address'], 255),
            'country': sanitize_string(form_data['billing-country'], 2),
            'state': sanitize_string(form_data['billing-state'], 128),
            'postal_code': sanitize_string(form_data['billing-zip'], 20),
        }
        
        # Save the updated customer information to Stripe
        customer.save()
        current_app.logger.info("Successfully updated customer billing information for user ID %s.", user.id)
        
        return True
    except Exception as e:
        # Log the exception with error level logging
        current_app.logger.error("Failed to update customer billing information for user ID %s. Error: %s", user.id, str(e))
        
        return False

def create_and_attach_payment_method(user, form_data):
    """
    Create and attach a payment method for a user using provided form data.

    Args:
        user (User): The user object containing user-specific data.
        form_data (dict): Form data containing payment and billing details.

    Returns:
        tuple: A tuple containing a boolean indicating success or failure, and an error message if applicable.
    """

    current_app.logger.info("Starting creation and attachment of payment method.")

    # Sanitize and set card name from form data
    card_name = sanitize_string(form_data['card-name'], 30)

    try:
        # Create the payment method with Stripe
        payment_method = stripe.PaymentMethod.create(
            type="card",
            card={"token": form_data['stripeToken']},
            billing_details={
                'name': card_name,
                'email': user.email,
                'address': {
                    'line1': sanitize_string(form_data['billing-address'], 255),
                    'country': sanitize_string(form_data['billing-country'], 2),
                    'state': sanitize_string(form_data['billing-state'], 128),
                    'postal_code': sanitize_string(form_data['billing-zip'], 20),
                }
            }
        )
        current_app.logger.info(f"Created new payment method for user ID {user.id}.")

        # Attach the payment method to the customer
        stripe.PaymentMethod.attach(
            payment_method.id,
            customer=user.stripe_customer_id,
        )
        current_app.logger.info(f"Attached payment method to customer for user ID {user.id}.")

        # Set the new payment method as the default
        stripe.Customer.modify(
            user.stripe_customer_id,
            invoice_settings={
                'default_payment_method': payment_method.id,
            },
        )
        current_app.logger.info(f"Set new payment method as default for user ID {user.id}.")

        return True, None

    except stripe.error.CardError as e:
        # Handle card-specific errors
        error_body = e.json_body
        card_err = error_body.get('error', {})
        error_message = card_err.get('message', 'Problem with card.')
        current_app.logger.warning(f"Card error for user ID {user.id}. Error: {error_message}")
        return False, error_message

    except stripe.error.StripeError as e:
        # Handle other Stripe-specific errors
        current_app.logger.error(f"Stripe error for user ID {user.id}. Error: {str(e)}")
        return False, str(e)

    except Exception as e:
        # Handle general errors
        current_app.logger.error(f"Unexpected error for user ID {user.id}. Error: {str(e)}")
        return False, str(e)

def load_sms_history(user_id, subscription_id, order='asc'):
    """
    Load SMS history for a specific user and subscription from the database.
    
    Args:
        user_id (int): ID of the user whose SMS history is to be retrieved.
        subscription_id (int): ID of the subscription linked to the SMS history.
        order (str, optional): Order of the returned messages. Default to 'asc'.
            'asc' returns messages from oldest to newest,
            'desc' returns messages from newest to oldest.
    
    Returns:
        list: A list of History records ordered as specified.
    
    Raises:
        ValueError: If the 'order' parameter is not 'asc' or 'desc'.
    """
    # Validate the order parameter to prevent SQL injection or errors.
    if order not in ['asc', 'desc']:
        current_app.logger.error("Invalid order value: {}".format(order))
        raise ValueError("Order must be 'asc' or 'desc'")
    
    current_app.logger.debug("Loading SMS history for user_id {} with subscription_id {}".format(user_id, subscription_id))
    
    # Build the query based on user_id and subscription_id
    query = History.query.filter_by(user_id=user_id, subscription_id=subscription_id)
    
    # Order the query by the 'created' field, either ascending or descending
    if order == 'asc':
        query = query.order_by(History.created.asc())
        current_app.logger.info("Ordered SMS history in ascending order.")
    else:
        query = query.order_by(History.created.desc())
        current_app.logger.info("Ordered SMS history in descending order.")
    
    # Fetch and return the results of the query
    result = query.all()
    current_app.logger.debug("Retrieved {} records from the database.".format(len(result)))
    return result

def delete_twilio_number(twilio_number_sid, twilio_client):
    """
    Deletes a Twilio phone number based on its SID.
    
    Args:
    twilio_number_sid (str): The SID of the Twilio phone number to be deleted.
    twilio_client (object): Instance of the Twilio client used to interact with Twilio API.
    
    Returns:
    bool: True if deletion was successful, False otherwise.
    """
    try:
        # Attempt to delete the phone number using its SID
        twilio_client.incoming_phone_numbers(twilio_number_sid).delete()
        current_app.logger.info(f"Deleted phone number with SID: {twilio_number_sid}")
        return True
    except Exception as e:
        # Log the exception details if deletion fails
        current_app.logger.error(f"Failed to delete phone number with SID: {twilio_number_sid}. Error: {e}")
        return False

def search_and_buy_sms_number(target_phone_number, twilio_client, country_code, base_url):
    """
    Search for and purchase an SMS-capable phone number near a given target number.

    Parameters:
        target_phone_number (str): The phone number near which to search for available numbers.
        twilio_client (object): Twilio client object used to interact with the Twilio API.
        country_code (str): ISO country code where the search should be performed.
        base_url (str): Base URL for the callback endpoint.

    Returns:
        tuple: A tuple containing the purchased phone number and its SID if available, otherwise (None, None).
    """
    # Convert the country code to uppercase to avoid case sensitivity issues with the API.
    country_code = country_code.upper()

    # Log the start of the number search process.
    current_app.logger.info(f'Starting search for SMS-enabled phone numbers near: {target_phone_number} in {country_code}')

    # Retrieve a list of available phone numbers that are SMS-enabled.
    numbers = twilio_client.available_phone_numbers(country_code).local.list(
        near_number=target_phone_number,
        sms_enabled=True,
        limit=5
    )

    # Check if any numbers are available.
    if numbers:
        # Select the first available number.
        chosen_number = numbers[0].phone_number

        # Log the chosen number before attempting purchase.
        current_app.logger.debug(f'Attempting to purchase phone number: {chosen_number}')

        # Purchase the selected phone number.
        purchased_number = twilio_client.incoming_phone_numbers.create(
            phone_number=chosen_number,
            sms_url=f'{base_url}/api/sms/callback'
        )

        # Log the successful purchase of the number.
        current_app.logger.info(f'Purchased phone number: {purchased_number.phone_number}')
        current_app.logger.info(f'Number SID: {purchased_number.sid}')

        return purchased_number.phone_number, purchased_number.sid
    else:
        # Log if no numbers are available.
        current_app.logger.warning(f'No SMS-enabled numbers available near {target_phone_number}')
        return None, None
	
def handle_stripe_operations(user, form_data, referrer, url_base):
    try:
        current_app.logger.info("Starting Stripe operations for user: %s", user.id)

        if not user.stripe_customer_id:
            raise ValueError("Stripe customer ID not found for user.")

        current_app.logger.info("Retrieved Stripe customer ID: %s", user.stripe_customer_id)

        update_customer = update_customer_billing_info(user, form_data)

        if not update_customer:
            return False, 'Error saving Stripe Customer', -1

        # Conditionally apply tax rates based on the billing country
        tax_rate_ids = get_tax_rate_ids(form_data['billing-country'])
        current_app.logger.info("Retrieved tax rate IDs: %s", tax_rate_ids)

        payment_info_update, payment_info_error = create_and_attach_payment_method(user, form_data)	    

        if not payment_info_update:
            return False, payment_info_error, -1
		
        # Create or update the Stripe subscription
        subscription = stripe.Subscription.create(
            customer=user.stripe_customer_id,
            items=[{'price': form_data['subscriptionOption']}],
            default_tax_rates=tax_rate_ids,
            expand=['latest_invoice.payment_intent', 'latest_invoice'],
        )
        current_app.logger.info("Created new subscription.")

        # Check if the payment was successful
        payment_intent = subscription.latest_invoice.payment_intent
        if payment_intent.status != 'succeeded':
            stripe.Subscription.delete(subscription.id)
            raise ValueError("Payment was not successful.")
        current_app.logger.info("Payment was successful.")

        # Extract necessary fields from the subscription
        subscription_id = subscription.id
        current_period_start = datetime.utcfromtimestamp(subscription.current_period_start).strftime('%Y-%m-%d %H:%M:%S')
        current_period_end = datetime.utcfromtimestamp(subscription.current_period_end).strftime('%Y-%m-%d %H:%M:%S')
        status = subscription.status.capitalize()

        stripe_product = stripe.Product.retrieve(id=subscription.plan.product)

        stripe_product_country = stripe_product.metadata.get('country', '')

        # Clean phone number and save it
        clean_number = clean_phone_number(form_data['user-mobile'])
        mobile_number = '+1'+str(clean_number)

        # Get Twilio number and SID (replace with appropriate function)
        twilio_client = Client(current_app.config['TWILIO_ACCOUNT_SID'], current_app.config['TWILIO_AUTH_TOKEN'])
        twilio_numr, twilio_sid = search_and_buy_sms_number(mobile_number, twilio_client, str(stripe_product_country), url_base)

        current_app.logger.info("handle_stripe_operations: Creating New subscription record.")
	    
        # Create a new Subscription record in the database
        new_subscription = Subscription(
            user_id=user.id,
            stripe_customer_id=user.stripe_customer_id,
            stripe_plan_id=subscription.plan.id,
            stripe_product_id=subscription.plan.product,
            twillio_number=twilio_numr,
            twillio_number_sid=twilio_sid,
            stripe_subscription_id=subscription.id,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
            status=status,
            referrer=referrer
        )

        # Add the new subscription to the database
        db.session.add(new_subscription)
        db.session.commit()
        current_app.logger.info("New subscription record added to the database.")

        subscription_id = new_subscription.id

        current_app.logger.info('Subscription created successfully for user: %s', user.id)
        return True, None, subscription_id

    except stripe.error.StripeError as e:
        current_app.logger.error(f'Stripe error: {e.user_message}')
        return False, e.user_message, -1
    except Exception as e:
        current_app.logger.error(f'Error: {str(e)}')
        return False, str(e), -1
	    

def update_billing_info(user, form_data):
    current_app.logger.info("update_billing_info()")
    card_name = sanitize_string(form_data['card-name'], 30)
    try:
        if not user.stripe_customer_id:
            # Raise an exception if the Stripe customer ID does not exist
            raise ValueError("Stripe customer ID not found for user.")

        # Retrieve the existing customer and update the billing information
        customer = stripe.Customer.retrieve(user.stripe_customer_id)
        customer.name = card_name
        customer.email = user.email
        customer.address = {
            'line1': sanitize_string(form_data['billing-address'], 255),
            'country': sanitize_string(form_data['billing-country'], 2),
            'state': sanitize_string(form_data['billing-state'], 128),
            'postal_code': sanitize_string(form_data['billing-zip'], 20),
        }
        customer.save()

        # Save the current default payment method
        old_payment_method = customer.invoice_settings.default_payment_method

        # Convert token to PaymentMethod and attach it to the customer
        payment_method = stripe.PaymentMethod.create(
            type="card",
            card={"token": form_data['stripeToken']},
            billing_details={
                'name': form_data['card-name'],
                'email': user.email,
                'address': {
                    'line1': sanitize_string(form_data['billing-address'], 255),
                    'country': sanitize_string(form_data['billing-country'], 2),
                    'state': sanitize_string(form_data['billing-state'], 128),
                    'postal_code': sanitize_string(form_data['billing-zip'], 20),
                }
            }
        )

        # Attach the new payment method to the customer
        stripe.PaymentMethod.attach(
            payment_method.id,
            customer=user.stripe_customer_id,
        )

        # Set the new payment method as the default
        stripe.Customer.modify(
            user.stripe_customer_id,
            invoice_settings={
                'default_payment_method': payment_method.id,
            },
        )

        # Conditionally apply tax rates based on the billing country
        tax_rate_ids = get_tax_rate_ids(form_data['billing-country'])

        # Pay any outstanding invoices immediately
        invoices = stripe.Invoice.list(customer=user.stripe_customer_id, status='open')
        for invoice in invoices:
            try:
                stripe.Invoice.pay(invoice.id)
            except stripe.error.StripeError as pay_error:
                current_app.logger.error(f'Error paying invoice {invoice.id}: {pay_error.user_message}')

        # Delete the old payment method if the new one works without issues
        if old_payment_method:
            stripe.PaymentMethod.detach(old_payment_method)

        current_app.logger.info('Billing Information Updated and outstanding invoices paid.')
        return True, None

    except stripe.error.StripeError as e:
        current_app.logger.error(f'Stripe error: {e.user_message}')
        
        # Detach the new payment method if it was successfully created and attached
        try:
            if payment_method and payment_method.customer:
                stripe.PaymentMethod.detach(payment_method.id)
        except Exception as detach_error:
            current_app.logger.error(f'Error detaching new payment method: {detach_error}')
            
        # Set the old payment method as the default if there was one
        if old_payment_method:
            stripe.Customer.modify(
                user.stripe_customer_id,
                invoice_settings={
                    'default_payment_method': old_payment_method,
                },
            )
        return False, e.user_message
    except Exception as e:
        current_app.logger.error(f'Error: {str(e)}')
        return False, str(e)


def save_user_and_assistant_preferences(user, subscription_id, form_data):
    try:
        # Get location details
        location_dict = get_location(form_data['user-location'])
        if location_dict and location_dict.get('location_text') != 'null':
            location_user = location_dict['location_text']
            location_country = location_dict['country_code']
        else:
            location_user = form_data['user-location']
            location_country = form_data['billing-country']
        
        # Save assistant preferences
        new_assistant_preference = AssistantPreference(
            user_id=user.id,
            subscription_id=subscription_id,
            assistant_name=sanitize_string(form_data['assistant-name'], 64),
            assistant_origin=sanitize_string(form_data['assistant-origin'], 64),
            assistant_gender=sanitize_string(form_data['assistant-gender'], 64),
            assistant_personality=sanitize_string(form_data['assistant-personality'], 64),
            assistant_response_style=sanitize_string(form_data['assistant-response-style'], 64)
        )
        db.session.add(new_assistant_preference)
        
        # Save user preferences
        new_user_preference = UserPreference(
            user_id=user.id,
            subscription_id=subscription_id,
            user_name=sanitize_string(form_data['user-name'], 64),
            user_title=sanitize_string(form_data['user-title'], 64),
            user_measurement=sanitize_string(form_data['user-measurement'], 64),
            user_bio=sanitize_string(form_data.get('user-description', ''), 512),
            user_language=sanitize_string(form_data['user-language'], 64),
            user_location_full=sanitize_string(location_user, 64), 
            user_location_country=sanitize_string(location_country, 3)
        )
        db.session.add(new_user_preference)
        
        # Commit preferences
        db.session.commit()
        
        # Clean phone number and save it
        clean_number = clean_phone_number(form_data['user-mobile'])
        ctry_code = 1  # Assuming country code is 1
        
        new_mobile_number = MobileNumber(
            user_id=user.id,
            subscription_id=subscription_id,
            country_code=ctry_code,
            mobile_number=int(clean_number)
        )
        db.session.add(new_mobile_number)
        
        # Commit mobile number
        db.session.commit()
        
        current_app.logger.info("Saved user and assistant preferences for user ID %s.", user.id)
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error("Failed to save user and assistant preferences for user ID %s. Error: %s", user.id, str(e))
        return False
    
    return True


def get_tax_rate_ids(country_code):
    tax_rate_ids = []
    if country_code == 'CA': 
        tax_rates = stripe.TaxRate.list(active=True)
        current_app.logger.error("get_tax_rate_ids: "+str(tax_rates))
        for tax_rate in tax_rates.data:  
            if tax_rate.country == 'CA':
                tax_rate_ids.append(tax_rate.id)
    return tax_rate_ids


def send_new_subscription_communications(subscription_id):
    # Retrieve subscription, user preferences, and assistant preferences
    subscription = Subscription.query.filter_by(id=subscription_id, enabled=True).first()
    user = User.query.filter_by(id=subscription.user_id).first()
    user_preferences = UserPreference.query.filter_by(user_id=subscription.user_id, subscription_id=subscription.id).first()
    assistant_preferences = AssistantPreference.query.filter_by(user_id=subscription.user_id, subscription_id=subscription.id).first()
    mobile = MobileNumber.query.filter_by(user_id=subscription.user_id, subscription_id=subscription.id).first()

    # Build system prompt for the welcome message
    sys_prompt = build_system_prompt(
        user_preferences,
        assistant_preferences,
        extra_info=None,
        system_message='Create an initial introduction and welcome message for your user in their preffered language.'
    )

    # Generate the welcome message
    welcome_message = build_and_send_messages_openai(sys_prompt, history_records=None)

    # Send the welcome message
    send_reply(
        user_id=subscription.user_id,
        subscription_id=subscription_id,
        reply=welcome_message,
        to_number='+1'+str(mobile.mobile_number),
        from_number=subscription.twillio_number,
        twilio_client=Client(current_app.config['TWILIO_ACCOUNT_SID'], current_app.config['TWILIO_AUTH_TOKEN']),
        save_message=True
    )

    # Send new subscription email
    send_new_subscription_email(
        user_name=user.name,
        user_email=user.email,
        user_number='+1'+str(mobile.mobile_number),
        assistant_name=assistant_preferences.assistant_name,
        assistant_number=subscription.twillio_number
    )
	
                
def clean_phone_number(phone_number):
    # Remove all non-numeric characters
    clean_number = re.sub(r'\D', '', phone_number)
    return clean_number

def get_country_code(phone_number):
    # Parse the phone number
    parsed_number = phonenumbers.parse(phone_number, "US")  # Default region as "US" for North America
    # Extract the country code
    country_code = parsed_number.country_code
    return country_code

def get_location(location_txt):
    try:
        client = Groq()
        completion = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {
                    "role": "system",
                    "content": "Convert the users input into a Location Full Text(City, State or Province, Country) and Country ISO Code( ISO 3166-1 alpha-2). If the location does not match, respond with null.\n\nRespond in a JSON Format with 2 fields (location_text, country_code) and no other text."
                },
                {
                    "role": "user",
                    "content": json.dumps(location_txt, indent=2)
                }
            ],
            temperature=1,
            max_tokens=128,
            top_p=1,
            stream=False,
            stop=None,
        )

        output = completion.choices[0].message.content

        return json.loads(output)

    except Exception as e:
        print(f"Error occurred: {e}")
        return False


def validate_incomming_message(from_number, phone_sid):
    try:
        # Parse the phone number to extract the country code and mobile number
        parsed_number = phonenumbers.parse(from_number)
        country_code = parsed_number.country_code
        mobile_number = parsed_number.national_number

        # Find the subscription using the account SID and from_number
        subscription = Subscription.query.filter_by(
            twillio_number_sid=phone_sid,
            enabled=1,
            billing_error=0
        ).first()

        if not subscription.user_id or not subscription.id or not subscription:
            current_app.logger.error(f"No subscription found for Twilio Number SID: {phone_sid}")
            return None, None

        # Check if the user_id and subscription_id match in the MobileNumber table
        mobile_entry = MobileNumber.query.filter_by(
            user_id=subscription.user_id,
            subscription_id=subscription.id,
            country_code=country_code,
            mobile_number=mobile_number
        ).first()

        if not mobile_entry:
            current_app.logger.error(f"No matching mobile number found for User ID: {subscription.user_id}, Subscription ID: {subscription.id}, From Number: {from_number}")
            return None, None

        user_id = subscription.user_id
        subscription_id = subscription.id

        return user_id, subscription_id
    except Exception as e:
        current_app.logger.error(f"Error in validate_incomming_message: {e}")
        return None, None


def save_sms_history(user_id, subscription_id, message_sid, direction, from_number, to_number, body=None, status=None):
    current_app.logger.debug(f"save_sms_history() called with user_id={user_id}, subscription_id={subscription_id}, message_sid={message_sid}, direction={direction}, from_number={from_number}, to_number={to_number}, body={body}, status={status}")

    # Create a new History instance
    try:
        history_record = History(
            user_id=user_id,
            subscription_id=subscription_id,
            message_sid=message_sid,
            direction=direction,
            from_number=from_number,
            to_number=to_number,
            body=body,
            status=status
        )
        current_app.logger.debug("History record created successfully")

        # Add the record to the session
        db.session.add(history_record)
        current_app.logger.debug("History record added to the session")

        # Commit the session to the database
        db.session.commit()
        current_app.logger.info("History record committed to the database successfully")
        return True
    except Exception as e:
        # Handle any exceptions that occur during commit
        db.session.rollback()
        current_app.logger.error(f"Error saving history record: {e}", exc_info=True)
        return False


def build_system_prompt(user_preferences, assistant_preferences, extra_info=None, system_message = None):
    """Builds a system prompt.

    Args:
        user_preferences: An instance of UserPreference.
        assistant_preferences: An instance of AssistantPreference.
        extra_info: Additional information to append at the end of the prompt. Can be a string, a list of strings, or None.

    Returns:
        A JSON-safe string containing the system prompt.
    """
    current_time_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    system_prompt = (
        f"You are a virtual SMS assistant named {assistant_preferences.assistant_name}, known for your {assistant_preferences.assistant_personality} personality. "
        f"Originating from {assistant_preferences.assistant_origin}, you were activated on {assistant_preferences.created} and have been learning and evolving ever since. "
        f"You identify as {assistant_preferences.assistant_gender}.\n\n"
    
        f"Your user is {user_preferences.user_name}, a {user_preferences.user_title}, who communicates with you primarily via SMS on the phone number associated with their subscription. "
        f"They reside in {user_preferences.user_location_full}, {user_preferences.user_location_country}. They speak {user_preferences.user_language} and expect you to assist them in that language, "
        f"and with a {assistant_preferences.assistant_response_style} response style. {user_preferences.user_name} is described as {user_preferences.user_bio}.\n\n"
    
        f"As an assistant, your main tasks are to comprehend the context, anticipate needs, and provide well-rounded, prompt responses in simple SMS format. "
        f"You are expected to always tell the truth, never embellish your capabilities, and ensure your responses are stripped of any markup, although URLs should remain functional. "
        f"Your responses should maintain the illusion of being a human assistant, yet make it clear that you are limited to retrieving data from the internet and sending links as needed."
        f"You can provide links and url's to the user if they ask for them, even if you do not have live data. For example links to google maps, amazon, google search, the weather network, and simmilar are acceptable. You may even generate links with searches built into them."
        f"When users ask for maps, feel free to give them links to maps, when users ask for directions, give them links to google maps with the destination selected. If the user asks for other infomation that can be provided by link, provide the link without being directly asked.\n\n"
    
        f"Current UTC Time: {current_time_utc}\n"
        f"Users Location: {user_preferences.user_location_full}\n"
        f"Preferred measurement system: {user_preferences.user_measurement}\n"
    )


    if extra_info:
        if isinstance(extra_info, str):
            extra_info_str = extra_info
        elif isinstance(extra_info, list):
            extra_info_str = "\n".join(extra_info)
        else:
            extra_info_str = str(extra_info)
        system_prompt += f"\n\nUse this additional Information to answer user questions. It is current search results. \nAdditional Information:\n{extra_info_str}"

    if system_message and not extra_info:
        
        system_prompt += f"\n\nResponse Message Type:\n{system_message}"

    return json.dumps(system_prompt)


def build_and_send_messages_openai(system_prompt, history_records=None):
    """
    Builds a list of messages for the conversation, placing the system prompt as the second last message, and sends them using the OpenAI client.

    Args:
        system_prompt: The system prompt in JSON format.
        history_records: List of History records.
          
    Returns:
        The assistant's response.
    """
    
    # Initialize the messages list
    messages = []

    if history_records:
        # Take the 6 most recent messages
        recent_history = history_records[:6]
        
        reversed_history = list(reversed(recent_history))  # Reverse to maintain chronological order
    
        # Process history records to build the conversation
        for record in reversed_history:
            role = "user" if record.direction == 'incoming' else "assistant"
            cleaned_record_body = clean_string(record.body)
            messages.append({"role": role, "content": [{"type": "text", "text": cleaned_record_body}]})
    
    # Insert the system prompt as the second last message
    system_message = {"role": "system", "content": [{"type": "text", "text": system_prompt}]}
    if messages:
        messages.insert(-3, system_message)
    else:
        messages.append(system_message)
    
    cleaned_messages = json.loads(json.dumps(messages))

    current_app.logger.debug(f"build_and_send_messages: messages: {cleaned_messages}")

    # Initialize OpenAI client and create a completion
    client = OpenAI(api_key=current_app.config['OPEN_AI_KEY'])
    completion = client.chat.completions.create(
        model=current_app.config['OPEN_AI_MODEL'],
        messages=cleaned_messages,
        temperature=1,
        max_tokens=1024,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0
    )

    output = clean_string(completion.choices[0].message.content)

    current_app.logger.debug(f"{output}")

    # Return the output content
    return json.loads(json.dumps(output))

def build_and_send_messages(system_prompt, history_records):
    """
    Builds a list of messages for the conversation and sends them using the Groq client.

    Args:
        system_prompt: The system prompt in JSON format.
        history_records: List of History records.

    Returns:
        The assistant's response.
    """
    # Order history records by created date in descending order to get the newest messages first
    sorted_history = sorted(history_records, key=lambda x: x.created, reverse=True)
    current_app.logger.debug(f"build_and_send_messages: 1")
    # Take the 8 most recent messages
    recent_history = sorted_history[:6]
    current_app.logger.debug(f"build_and_send_messages: 2")
    # Build the messages list
    messages = [{"role": "system", "content": system_prompt}]
    current_app.logger.debug(f"build_and_send_messages: 3")
    # Process history records to build the conversation

    for record in reversed(recent_history):  # Reverse to maintain chronological order
        if record.direction == 'incoming':
            role = "user" 
        else:
            role = "assistant"
        cleaned_record_body = clean_string(record.body)
        messages.append({"role": role, "content": cleaned_record_body})
    current_app.logger.debug(f"build_and_send_messages: 4")

    cleaned_messages = json.loads(json.dumps(messages))

    current_app.logger.debug(f"build_and_send_messages: messages: {cleaned_messages}")

    # Initialize Groq client and create a completion
    client = Groq()
    completion = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=cleaned_messages,
        temperature=1,
        max_tokens=1024,
        top_p=1,
        stream=False,
        stop=None,
    )

    current_app.logger.debug(f"build_and_send_messages: 5")

    current_app.logger.debug(f"{completion.choices[0].message}")
    
    output = completion.choices[0].message.content

    current_app.logger.debug(f"{output}")

    # Return the output content
    return json.loads(json.dumps(output))

def send_reply(user_id, subscription_id, reply, to_number, from_number, twilio_client, save_message=True):
    """Sends a reply to the user, handling multipart messages if necessary.

    Args:
        user_id: The user's ID.
        subscription_id: The subscription ID.
        reply: The reply to send.
        to_number: The user's phone number.
        from_number: The Twilio phone number to send the message from.
        twilio_client: The Twilio Client object for sending the message.
    """
    try:
        # Log initial input parameters
        current_app.logger.debug(f"send_reply: user_id {user_id}, subscription_id {subscription_id}, to_number {to_number}, from_number {from_number}")
        current_app.logger.debug(f"send_reply: original_reply {reply}")

        # Clean the reply string
        reply = clean_string(reply)
        current_app.logger.debug(f"send_reply: cleaned_reply {reply}")

        # Check if message length exceeds Twilio's limit for a single message
        if len(reply) > 1600:
            # Split the message into parts of length less than or equal to 1600
            reply_parts = [reply[i:i+1600] for i in range(0, len(reply), 1600)]
        else:
            reply_parts = [reply]

        # Send each part as a separate message
        sent_sids = []
        for part in reply_parts:
            sent = twilio_client.messages.create(
                body=part,
                from_=from_number,
                to=to_number
            )
            sent_sids.append(sent.sid)
            current_app.logger.debug(f"send_reply: Twilio response SID {sent.sid} for part: {part}")
            current_app.logger.info(f"Message sent to {to_number} from {from_number}: {part}")

        # If there are multiple parts, save the sids as an array
        if len(sent_sids) > 1:
            sent_sid = sent_sids
        else:
            sent_sid = sent_sids[0]

    except Exception as e:
        # Log any errors that occur
        current_app.logger.error(f"send_reply: Error sending message to {to_number} from {from_number}: {str(e)}")
        current_app.logger.error("send_reply: Exception details")
        sent_sid = None

    # Save the SMS history
    if save_message:
        save_sms_history(user_id, subscription_id, str(sent_sid), 'outgoing', from_number, to_number, reply, 'sent')
	    
def handle_payment_success(invoice):
    subscription_id = invoice['subscription']
    payment_date = datetime.fromtimestamp(invoice['created'])
    last_payment_amount = invoice['amount_paid'] / 100  # Stripe amount is in cents

    retries = 0
    max_retries = 5
    subscription_record = None

    while retries < max_retries and subscription_record is None:
        try:
            current_app.logger.info(f"Attempt {retries + 1}: Trying to retrieve and process subscription {subscription_id}.")
            subscription = stripe.Subscription.retrieve(subscription_id)
            current_period_start = datetime.fromtimestamp(subscription['current_period_start'])
            current_period_end = datetime.fromtimestamp(subscription['current_period_end'])

            subscription_record = Subscription.query.filter_by(stripe_subscription_id=subscription_id, enabled=True).first()

            if subscription_record:
                had_billing_issue = getattr(subscription_record, 'billing_error', False) or False
                subscription_record.enabled = True
                subscription_record.billing_error = False
                subscription_record.status = 'Active'
                subscription_record.current_period_start = current_period_start
                subscription_record.current_period_end = current_period_end
                subscription_record.last_payment_amount = last_payment_amount
                subscription_record.last_payment_date = payment_date
                db.session.commit()
                current_app.logger.info(
                    f"Subscription {subscription_id} updated successfully with payment details."
                )

                if had_billing_issue:
                    current_app.logger.info(f"Handling previous billing issues for subscription {subscription_id}.")
                    # The implementation details for notifications and prompts would remain the same
                    # Place the existing code for handling billing issues here

            else:
                current_app.logger.info(f"No active subscription record found for {subscription_id}. Retrying...")
                retries += 1
                time.sleep(2)  # Wait for 2 seconds before trying again

        except Exception as e:
            current_app.logger.error(f"An error occurred while processing subscription {subscription_id}: {str(e)}")
            retries += 1
            time.sleep(2)  # Wait before retrying

    if not subscription_record:
        current_app.logger.error(
            f"handle_payment_success: Subscription with ID {subscription_id} not found after {max_retries} retries."
        )

def handle_billing_issue(invoice):
    """
    Handle billing issues by updating the subscription status and notifying the user.
    
    Args:
    invoice (dict): A dictionary containing invoice details with a 'subscription' key.

    This function queries the Subscription model to find an active subscription matching
    the provided subscription ID from the invoice. If found, it updates the subscription's
    status to indicate a billing error and notifies the user via their registered mobile number(s).
    """
    subscription_id = invoice['subscription']
    # Query the database for an active subscription with the provided ID
    subscription_record = Subscription.query.filter_by(stripe_subscription_id=subscription_id, enabled=True).first()

    if subscription_record:
        # Update subscription record with billing issue status
        subscription_record.billing_error = True
        subscription_record.status = 'Billing Issue'
        db.session.commit()

        # Log successful update
        current_app.logger.debug(f"Subscription {subscription_id} updated with billing error status.")

        # Retrieve user and assistant preferences for building the system prompt
        user_preferences = UserPreference.query.filter_by(user_id=subscription_record.user_id, subscription_id=subscription_record.id).first()	 
        assistant_preferences = AssistantPreference.query.filter_by(user_id=subscription_record.user_id, subscription_id=subscription_record.id).first()
        
        # Retrieve all mobile numbers associated with the subscription
        mobile_entries = MobileNumber.query.filter_by(user_id=subscription_record.user_id, subscription_id=subscription_record.id).all()
        
        # Build system prompt for notifying the user about the billing issue
        sys_prompt = build_system_prompt(user_preferences, assistant_preferences, extra_info=None, system_message=f'Tell the user that their account had a billing issue and to fix it they need to update their payment info on {request.url_root[:-1]}. Until then you will not be available to them, nor will you be able to help them resolve the issue.')
        
        # Send the billing issue message to OpenAI and receive the response
        billing_issue_message = build_and_send_messages_openai(sys_prompt, history_records=None)
        
        # Send the message to all user's mobile numbers
        for mobile_entry in mobile_entries:
            send_reply(subscription_record.user_id, subscription_record.id, billing_issue_message, mobile_entry.mobile_number, subscription_record.twillio_number, Client(current_app.config['TWILIO_ACCOUNT_SID'], current_app.config['TWILIO_AUTH_TOKEN']), save_message=False)
	    
        current_app.logger.info(f"handle_billing_issue: Notified user(s) of the billing issue for subscription ID {subscription_id}.")
    else:
        # Log when no active subscription is found
        current_app.logger.warning(f"handle_billing_issue: Active subscription with ID {subscription_id} not found.")


def handle_subscription_cancellation(subscription):
    # Extract the subscription ID from the subscription dictionary
    subscription_id = subscription['id']

    # Query the database for the active subscription record with the given ID
    subscription_record = Subscription.query.filter_by(
        stripe_subscription_id=subscription_id, enabled=True).first()
    user = User.query.filter_by(id=subscription_record.user_id).first()

    # If the subscription record is found, proceed with cancellation
    if subscription_record:
        # Initialize the Twilio client with credentials from the application config
        twilio_client = Client(
            current_app.config['TWILIO_ACCOUNT_SID'], current_app.config['TWILIO_AUTH_TOKEN']) 

        # Delete the associated Twilio number
        delete_twilio_number(subscription_record.twillio_number_sid, twilio_client)

        # Update the subscription record to reflect its cancellation
        subscription_record.enabled = False
        subscription_record.status = 'Cancelled'
        subscription_record.twillio_number = None
        subscription_record.twillio_number_sid = None
        db.session.commit()

        # Send an email to the user about the subscription ending
        send_end_subscription_email(user.name, user.email)
	    
        # Log the successful cancellation
        current_app.logger.info(
            f"handle_subscription_cancellation: Successfully updated subscription {subscription_id} "
            f"to 'Cancelled' status."
        )
    else:
        # Log the failure to find the subscription
        current_app.logger.warning(
            f"handle_subscription_cancellation: Subscription with ID {subscription_id} not found or already disabled"
        )

def send_email(to_email, subject, html_content, text_content):
    """
    Sends an email to a specified recipient.

    Args:
    to_email (str): The recipient's email address.
    subject (str): The subject line of the email.
    html_content (str): The HTML content of the email.
    text_content (str): The plain text content of the email.

    Returns:
    None
    """
    # Create a Mail object with necessary details
    email_message = Mail(
        from_email='support@improbability.io',
        to_emails=to_email,
        subject=subject,
        html_content=html_content,
        plain_text_content=text_content
    )

    try:
        # Retrieve SendGrid API client using the app's configuration
        sg_client = SendGridAPIClient(current_app.config['SENDGRID_API_KEY'])
        # Send the email and capture the response
        response = sg_client.send(email_message)
        # Log successful email transmission
        current_app.logger.info(f"send_email: Email sent! Status code: {response.status_code}")
    except Exception as error:
        # Log any errors during the email send process
        current_app.logger.error(f"send_email: Failed to send email: {error}")

def send_new_subscription_email(user_name, user_email, user_number, assistant_name, assistant_number):
    # Log the start of the email sending process
    current_app.logger.debug("Starting to send a new subscription email to {}".format(user_email))

    # Prepare email content and subject
    subject = "Meet Your New SMS AI Assistant from Improbability Labs!"
    html_content = render_template('emails/new_subscription.html', User_Name=user_name, User_Number=user_number, Assistant_Name=assistant_name, Assistant_Number=assistant_number)
    text_content = render_template('emails/new_subscription.txt', User_Name=user_name, User_Number=user_number, Assistant_Name=assistant_name, Assistant_Number=assistant_number)

    try:
        # Attempt to send the email
        send_email(user_email, subject, html_content, text_content)
        # Log the successful email sending
        current_app.logger.info("Successfully sent new subscription email to {}".format(user_email))
    except Exception as e:
        # Log any exception that occurs during the email sending
        current_app.logger.error("Failed to send new subscription email to {}. Error: {}".format(user_email, str(e)))

def send_end_subscription_email(user_name, user_email):
    """
    Send an email notification to a user about the end of their subscription.

    Args:
        user_name (str): The name of the user.
        user_email (str): The email address of the user.
    """
    # Define the email subject
    subject = "We're Sorry to See You Go"
    
    # Log the initiation of the email sending process
    current_app.logger.info(f"Initiating sending the end subscription email to {user_email}.")
    
    try:
        # Render the HTML content for the email
        html_content = render_template('emails/end_subscription.html', User_Name=user_name, User_Email=user_email)
        # Render the plain text content for the email
        text_content = render_template('emails/end_subscription.txt', User_Name=user_name, User_Email=user_email)
        
        # Send the email
        send_email(user_email, subject, html_content, text_content)
        
        # Log successful email sending
        current_app.logger.info(f"Email successfully sent to {user_email}.")
        
    except Exception as e:
        # Log any error during the email sending process
        current_app.logger.error(f"Failed to send email to {user_email}: {e}")
