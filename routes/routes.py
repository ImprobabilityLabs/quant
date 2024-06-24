from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort, current_app, Response
from flask_sitemap import Sitemap
from models import db, User, Subscription, MobileNumber, History, UserPreference, AssistantPreference 
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from oauthlib.oauth2 import WebApplicationClient
from requests_oauthlib import OAuth2Session
from utils.utility import fetch_data, check_user_subscription, generate_menu, get_products, handle_stripe_operations, get_country_code, clean_phone_number, validate_incomming_message, save_sms_history, load_sms_history, build_system_prompt, process_questions_answers, build_and_send_messages, send_reply, build_and_send_messages_openai, update_billing_info, format_phone_number, handle_payment_success, get_location, handle_billing_issue, handle_subscription_cancellation, send_end_subscription_email, save_user_and_assistant_preferences, send_new_subscription_communications
import stripe
import aiohttp
import asyncio
import openai
from datetime import datetime
from meta_tags import MetaTags

def configure_routes(app):

    sitemap = Sitemap(app=app)

    app.jinja_env.filters['format_phone_number'] = format_phone_number

    @app.context_processor
    def inject_analytics():
        return dict(
            google_analytics_id=app.config['GOOGLE_ANALYTICS_ID'],
            google_site_verification=app.config['GOOGLE_SITE_VERIFICATION'],
            bing_site_verification=app.config['BING_SITE_VERIFICATION']
        )

    @app.after_request
    def add_header(response):
        # Ensure the endpoint is not None before checking its value
        if request.endpoint and 'static' not in request.endpoint:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response
    
    @app.route('/robots.txt')
    def robots_txt():
        base_url = request.url_root[:-1]  # Remove the trailing slash
        lines = [
            "User-Agent: *",
            "Disallow: /dashboard",
            "Disallow: /subscribe",
            "Disallow: /account",
            "Disallow: /logout",
            "Disallow: /api",
            "Allow: /",
            "Allow: /about",
            "Allow: /contact",
            "Allow: /terms",
            "Allow: /privacy",
            "Allow: /faq",
            f"Sitemap: {base_url}/sitemap.xml"
        ]
        return Response("\n".join(lines), mimetype="text/plain")

    @app.route('/', methods=['GET', 'POST'])
    def index_page():
        referrer = request.args.get('referrer')
        if referrer:
            session['referrer'] = referrer
            current_app.logger.info(f'Referrer set to: {referrer}')
        if session.get('user_provider_id'):
            member = check_user_subscription(session.get('user_provider_id'))
            is_user = member['is_user']
        else:
            member = check_user_subscription(None)
            is_user = False
        product_data = get_products()
        current_app.logger.info('Info: Index Page - Member Object: ' + str(member))
        menu = generate_menu(member)
        return render_template('index.html', seometa=MetaTags, menu=menu, is_user=is_user, products=product_data)

    @app.route('/terms')
    def terms_page():
        if session.get('user_provider_id'):
            member = check_user_subscription(session.get('user_provider_id'))
        else:
            member = check_user_subscription(None)
        current_app.logger.info('Info: Terms Page - Member Object: ' + str(member))
        menu = generate_menu(member)
        return render_template('terms.html', seometa=MetaTags, menu=menu)

    @app.route('/privacy')
    def privacy_page():
        if session.get('user_provider_id'):
            member = check_user_subscription(session.get('user_provider_id'))
        else:
            member = check_user_subscription(None)
        current_app.logger.info('Info: Privacy Page - Member Object: ' + str(member))
        menu = generate_menu(member)
        return render_template('privacy.html', seometa=MetaTags, menu=menu)

    @app.route('/about')
    def about_page():
        if session.get('user_provider_id'):
            member = check_user_subscription(session.get('user_provider_id'))
        else:
            member = check_user_subscription(None)
        current_app.logger.info('Info: About Page - Member Object: ' + str(member))
        menu = generate_menu(member)
        return render_template('about.html', seometa=MetaTags, menu=menu)

    @app.route('/faq')
    def faq_page():
        if session.get('user_provider_id'):
            member = check_user_subscription(session.get('user_provider_id'))
        else:
            member = check_user_subscription(None)
        current_app.logger.info('Info: Faq Page - Member Object: ' + str(member))
        menu = generate_menu(member)
        return render_template('faq.html', seometa=MetaTags, menu=menu)
      
    @app.route('/contact', methods=['GET', 'POST'])
    def contact_page():
        if session.get('user_provider_id'):
            member = check_user_subscription(session.get('user_provider_id'))
        else:
            member = check_user_subscription(None)
        current_app.logger.info('Info: Contact Page - Member Object: ' + str(member))
        menu = generate_menu(member)
        return render_template('contact.html', seometa=MetaTags, menu=menu)

    @app.route('/subscribe', methods=['GET', 'POST'])
    def subscribe_page():
        if session.get('user_provider_id'):
            member = check_user_subscription(session.get('user_provider_id'))
        else:
            member = check_user_subscription(None)
        current_app.logger.info('Info: Subscribe Page - Member Object: ' + str(member))
        menu = generate_menu(member)
        if not member['is_user']:
            return redirect(url_for('index_page'))
        elif not member['is_subscribed']:
            error_message = None
            if request.method == 'POST':
                current_app.logger.info('Received POST request with following form data:')
                base_url = request.url_root[:-1]
                for key in request.form:
                    current_app.logger.info(f'{key}: {request.form[key]}')
                # Validate form data
                required_fields = [
                    'subscriptionOption', 'assistant-name', 'assistant-origin', 'assistant-gender',
                    'assistant-personality', 'assistant-response-style', 'user-name', 'user-location', 
                    'user-mobile', 'user-language', 'user-title', 'user-measurement', 'user-description', 
                    'card-name', 'billing-address', 'billing-country', 'billing-state', 'billing-zip', 
                    'stripeToken'
                ]
                    
                error_message = 'Please complete all required fields.'
                if all(field in request.form for field in required_fields):
                    user = User.query.filter_by(provider_id=session.get('user_provider_id')).first()
                    if user:
                        referrer = session.get('referrer', '')
                        success, error_message, subscription_id = handle_stripe_operations(user, request.form, referrer, base_url)
                        
                        if success:
                            if save_user_and_assistant_preferences(user, subscription_id, request.form):
                                send_new_subscription_communications(subscription_id)
                                
                                return redirect(url_for('dashboard_page'))
                    else:
                        current_app.logger.error(error_message)
                        
            product_data = get_products()
            current_app.logger.info('Info: Subscribe Page - Products Object: ' + str(product_data))
            return render_template('subscribe.html', seometa=MetaTags, menu=menu, products=product_data, form_data=request.form, STRIPE_PUB_KEY=current_app.config['STRIPE_PUB_KEY'], error=error_message)

    
    @app.route('/account', methods=['GET', 'POST'])
    def account_page():
        if session.get('user_provider_id'):
            member = check_user_subscription(session.get('user_provider_id'))
        else:
            member = check_user_subscription(None)
        current_app.logger.info('Info: Account Page - Member Object: ' + str(member))
        menu = generate_menu(member)
        if not member['is_user']:
            return redirect(url_for('index_page'))
        elif not member['is_subscribed']:
            return redirect(url_for('subscribe_page'))
        elif member['is_subscribed']:
            user = User.query.filter_by(provider_id=session.get('user_provider_id')).first()
            subscription = Subscription.query.filter_by(user_id=user.id, enabled=True).first()
            try:
                # show response area & error
                payment_error_msg = None
                show_response = None

                # Fetch customer subscriptions
                subscriptions = stripe.Subscription.list(customer=user.stripe_customer_id)

                # Retrieve customer information from Stripe
                customer_info = stripe.Customer.retrieve(user.stripe_customer_id)

                # Extract billing information
                payment_data = {
                    'card-name': customer_info['name'] if customer_info.get('name') else '',
                    'billing-address': customer_info['address']['line1'] if customer_info.get('address') else '',
                    'billing-country': customer_info['address']['country'] if customer_info.get('address') else '',
                    'billing-state': customer_info['address']['state'] if customer_info.get('address') else '',
                    'billing-zip': customer_info['address']['postal_code'] if customer_info.get('address') else ''
                }

                if request.method != 'POST':
                    # Retrieve customer information from Stripe
                    form_data = payment_data

                elif request.method == 'POST':
                    page_data = request.form
                    current_app.logger.info(f'page_data: {page_data}')  
                    if 'payment' in page_data:
                        form_data = page_data
                        payment_error, payment_error_msg = update_billing_info(user, form_data)
                        show_response = True
                        current_app.logger.info(f'{payment_error_msg}')
                        
                    else:
                        form_data = payment_data
 
                # Fetch the plan details from Stripe
                stripe_plan = stripe.Price.retrieve(subscription.stripe_plan_id)
                stripe_product = stripe.Product.retrieve(stripe_plan.product)
                
                # Format the dates
                start_date = subscription.current_period_start.strftime('%A, %B %d, %Y')
                end_date = subscription.current_period_end.strftime('%A, %B %d, %Y')

                # Determine the interval
                interval = 'Monthly' if stripe_plan.recurring['interval'] == 'month' else 'Yearly'

                # Find the subscription with the specified price ID
                subscription_id = subscription.stripe_subscription_id

                if subscription_id:
                    
                    if request.method == 'POST':
                        cancel_state = request.form.get('cancel-state')
                        if cancel_state == 'canceled':
                            stripe.Subscription.modify(
                                subscription_id,
                                cancel_at_period_end=True
                            )
                            subscription.status = "Canceling as of " + end_date
                            current_app.logger.info('Account: Cancel Subscription')
                            
                        elif cancel_state == 'not-canceled':
                            stripe.Subscription.modify(
                                subscription_id,
                                cancel_at_period_end=False
                            )
                            subscription.status = 'Active'
                            current_app.logger.info('Account: Re-Enable Subscription')
                            
                    cancel_details = stripe.Subscription.retrieve(subscription_id)

                    subscription_canceled = False
                    
                    if cancel_details['cancel_at_period_end']:
                        subscription_canceled = True
            
                    try:
                        db.session.commit()
                    except Exception as e:
                        db.session.rollback()
                        current_app.logger.error('Account: An error occurred while updating your subscription. Please try again.')
                        
           
                # Fetch invoices for the subscription
                invoices = stripe.Invoice.list(
                    customer=user.stripe_customer_id,
                    subscription=subscription_id,
                    limit=24  # Adjust the limit as needed
                )

                # Extract relevant data from each invoice
                invoice_data = []
                for invoice in invoices.auto_paging_iter():
                    invoice_data.append({
                        'number': invoice.number,
                        'type': 'Subscription',  # Assuming all invoices are for subscriptions
                        'date': datetime.fromtimestamp(invoice.created),
                        'amount': invoice.amount_due / 100,  # Convert cents to dollars
                        'status': invoice.status,
                        'receipt_url': invoice.hosted_invoice_url  # URL for the printable receipt
                    })

                subscription_details = {
                    'name': stripe_product.name,
                    'price': f"${stripe_plan.unit_amount / 100:.2f} {stripe_plan.currency.upper()}",
                    'interval': interval,
                    'current_period_start': start_date,
                    'current_period_end': end_date,
                    'status': subscription.status
                }
                current_app.logger.info(f"Account: form_data: {form_data}")
                return render_template('account.html', seometa=MetaTags, menu=menu, invoices=invoice_data, form_data=form_data, subscription_details=subscription_details, subscription_canceled=subscription_canceled, show_response=show_response, STRIPE_PUB_KEY=current_app.config['STRIPE_PUB_KEY'], payment_error_msg=payment_error_msg)
        
            except Exception as e:
                return jsonify({'error': str(e)}), 500


    @app.route('/dashboard', methods=['GET', 'POST'])
    def dashboard_page():
        if session.get('user_provider_id'):
            member = check_user_subscription(session.get('user_provider_id'))
        else:
            member = check_user_subscription(None)
        current_app.logger.info('Info: Dashboard Page - Member Object: ' + str(member))
        menu = generate_menu(member)
        if not member['is_user']:
            return redirect(url_for('index_page'))
        elif not member['is_subscribed']:
            return redirect(url_for('subscribe_page'))
        elif member['is_subscribed'] and not member['has_billing_error']:
            user = User.query.filter_by(provider_id=session.get('user_provider_id')).first()
            subscription = Subscription.query.filter_by(user_id=user.id, enabled=True).first()
            user_preferences = UserPreference.query.filter_by(user_id=user.id, subscription_id=subscription.id).first()
            assistant_preferences = AssistantPreference.query.filter_by(user_id=user.id, subscription_id=subscription.id).first()
            mobile = MobileNumber.query.filter_by(user_id=subscription.user_id, subscription_id=subscription.id).first()
            history_records = History.query.filter_by(user_id=user.id, subscription_id=subscription.id)\
                               .order_by(History.created.desc())\
                               .limit(120)\
                               .all()
            
            assistant_success = None
            user_success = None

            stripe_product = stripe.Product.retrieve(id=subscription.stripe_product_id)

            stripe_product_country = stripe_product.metadata.get('country', '')
            
            if request.method == 'POST':
                process_form = request.form.get('process-form')
                if process_form == 'assistant':
                    assistant_name = request.form.get('assistant-name', '').strip()[:64]  
                    assistant_origin = request.form.get('assistant-origin', '').strip()[:64]
                    assistant_gender = request.form.get('assistant-gender', '').strip()[:64] 
                    assistant_personality = request.form.get('assistant-personality', '').strip()[:64] 
                    assistant_response_style = request.form.get('assistant-response-style', '').strip()[:64]
                    
                    assistant_preferences.assistant_name = assistant_name
                    assistant_preferences.assistant_origin = assistant_origin
                    assistant_preferences.assistant_gender = assistant_gender
                    assistant_preferences.assistant_personality = assistant_personality
                    assistant_preferences.assistant_response_style = assistant_response_style
                    db.session.commit()
                    current_app.logger.info('Dashboard Page - Assistant Prefrences DB Updated')
                    assistant_success = True
                 
                elif process_form == 'user':
                    user_name = request.form.get('user-name', '').strip()[:64]  
                    user_title = request.form.get('user-title', '').strip()[:64]
                    user_measurement = request.form.get('user-measurement', '').strip()[:64]
                    user_bio = request.form.get('user-description', '').strip()[:512]  
                    user_language = request.form.get('user-language', '').strip()[:64]
                    user_mobile = clean_phone_number(request.form.get('user-mobile', ''))
                    location_dict = get_location(request.form['user-location'])
                    if location_dict:
                        if location_dict['location_text'] != 'null':
                            location_user = location_dict['location_text'].strip()[:64]  
                            location_country = location_dict['country_code'].strip()[:2]  
                        else:
                            location_user = request.form['user-location'].strip()[:64]  
                            location_country = user_preferences.user_location_country.strip()[:2]  
                    else:
                        location_user = request.form['user-location'].strip()[:64]  
                        location_country = user_preferences.user_location_country.strip()[:2]  
                    user_preferences.user_name = user_name
                    user_preferences.user_title = user_title
                    user_preferences.user_measurement = user_measurement
                    user_preferences.user_bio = user_bio
                    user_preferences.user_language = user_language
                    user_preferences.user_location_full = location_user 
                    user_preferences.user_location_country = location_country

                    mobile.mobile_number = user_mobile
                    
                    db.session.commit()
                    current_app.logger.info('Dashboard Page - User Prefrences DB Updated')
                    user_success = True
            
            assistant_details = {
                'name': assistant_preferences.assistant_name,
                'birthdate': datetime.strftime(assistant_preferences.created, "%A, %B %d, %Y"),
                'assistant_mobile_number': subscription.twillio_number,
                'user_mobile_number': '+1'+str(mobile.mobile_number),
                'status': subscription.status
            }

            assistant_preferences = {
                'name': assistant_preferences.assistant_name,
                'origin': assistant_preferences.assistant_origin,
                'gender': assistant_preferences.assistant_gender,
                'personality': assistant_preferences.assistant_personality,
                'response_style': assistant_preferences.assistant_response_style
            }            

            user_preferences = {
                'name': user_preferences.user_name,
                'title': user_preferences.user_title,
                'measurement': user_preferences.user_measurement,
                'bio': user_preferences.user_bio,
                'language': user_preferences.user_language,
                'user_mobile_number': str(mobile.mobile_number),
                'location_full': user_preferences.user_location_full
            }  
            
            return render_template('dashboard.html', seometa=MetaTags, menu=menu, history_records=history_records, assistant_details=assistant_details, assistant_preferences=assistant_preferences, user_preferences=user_preferences, user_success=user_success, assistant_success=assistant_success, stripe_product_country=stripe_product_country)
        elif member['is_subscribed'] and member['has_billing_error']:
            return redirect(url_for('account_page'))

    @app.route('/logout')
    def logout():
        # Save the referrer session variable locally
        referrer = session.get('referrer')

        # Clear all data from the session
        session.clear()
     
        # Redirect to login page
        response = redirect(url_for('index_page'))

        # Delete cookies
        for key in request.cookies:
            response.delete_cookie(key)
    
        # Recreate the referrer session variable
        if referrer:
            session['referrer'] = referrer
            current_app.logger.info(f'Referrer retained after logout: {referrer}')

        # Redirect to the homepage
        return response

    @app.route("/api/microsoft/authorize")
    def microsoft_authorize():
        current_app.logger.info('Info: API Call to /api/microsoft/authorize')
        client = OAuth2Session(current_app.config['MICROSOFT_CLIENT_ID'], scope=["openid", "profile", "email"], redirect_uri=url_for("microsoft_callback", _external=True, _scheme='https'))
        uri, state = client.authorization_url(current_app.config['MICROSOFT_AUTHORIZATION_URL'])
        return redirect(uri)

    @app.route("/api/microsoft/callback")
    def microsoft_callback():
        current_app.logger.info('Info: API Call to /api/microsoft/callback')
        client = OAuth2Session(current_app.config['MICROSOFT_CLIENT_ID'], scope=["openid", "profile", "email"], redirect_uri=url_for("microsoft_callback", _external=True, _scheme='https'))
        token = client.fetch_token(current_app.config['MICROSOFT_TOKEN_URL'], client_secret=current_app.config['MICROSOFT_CLIENT_SECRET'], authorization_response=request.url)
        user_info = client.get("https://graph.microsoft.com/oidc/userinfo").json()
        current_app.logger.info('Info: Data Received from Microsoft API Call to /api/microsoft/callback: '+ str(user_info))
        provider_id = user_info.get("sub")
        # Create a new user in the database if it doesn't exist
        user_name = user_info.get("name")
        if not user_name:
            user_name = user_info.get("givenname") + " " + user_info.get("familyname")
        user = User.query.filter_by(provider_id=provider_id).first()
        if not user:
            # Create a Stripe customer
            stripe_customer = stripe.Customer.create(
                email=user_info.get("email"),
                name=user_name,
                description="Customer for {}".format(user_info.get("email")),
            )
            user = User(
                provider_id=provider_id,
                email=user_info.get("email"),
                name=user_name,
                provider_name='microsoft',  # Set the provider as 'microsoft'
                profile_pic=user_info.get("picture", None),  # Use the 'picture' field from Microsoft, if available
                stripe_customer_id=stripe_customer.id  # Initialize as None; update when integrating with Stripe
            )
            db.session.add(user)
            db.session.commit()
        session["user_provider_id"] = provider_id
        return redirect(url_for("dashboard_page"))

    @app.route("/api/google/authorize")
    def google_authorize():
        current_app.logger.info('Info: API Call to /api/google/authorize')
        client = OAuth2Session(current_app.config['GOOGLE_CLIENT_ID'], scope=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"], redirect_uri=url_for("google_callback", _external=True, _scheme='https'))
        uri, state = client.authorization_url(current_app.config['GOOGLE_AUTHORIZATION_URL'])
        return redirect(uri)

    @app.route("/api/google/callback")
    def google_callback():
        current_app.logger.info('Info: API Call to /api/google/callback')
        client = OAuth2Session(current_app.config['GOOGLE_CLIENT_ID'], scope=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"], redirect_uri=url_for("google_callback", _external=True, _scheme='https'))
        token = client.fetch_token(current_app.config['GOOGLE_TOKEN_URL'], client_secret=current_app.config['GOOGLE_CLIENT_SECRET'], authorization_response=request.url)
        user_info = client.get("https://openidconnect.googleapis.com/v1/userinfo").json()
        provider_id = user_info.get("sub")
        # Create a new user in the database if it doesn't exist
        user = User.query.filter_by(provider_id=provider_id).first()
        if not user:
            # Create a Stripe customer
            stripe_customer = stripe.Customer.create(
                email=user_info.get("email"),
                name=user_info.get("name"),
                description="Customer for {}".format(user_info.get("email")),
            )
            user = User(
                provider_id=provider_id, 
                email=user_info.get("email"), 
                name=user_info.get("name"), 
                provider_name='google',  # Set the provider as 'google'
                profile_pic=user_info.get("picture", None),  # Use the 'picture' field from Google, if available
                stripe_customer_id=stripe_customer.id  # Initialize as None; update when integrating with Stripe
            )
            db.session.add(user)
            db.session.commit()
        session["user_provider_id"] = provider_id
        return redirect(url_for("dashboard_page"))



    @app.route('/api/sms/callback', methods=['POST'])
    def twilio_callback():
        try:
            # Create an instance of RequestValidator
            validator = RequestValidator(app.config['TWILIO_AUTH_TOKEN'])
     
            # Create an instance of Client
            client = Client(current_app.config['TWILIO_ACCOUNT_SID'], current_app.config['TWILIO_AUTH_TOKEN'])

            # Retrieve the full URL of the incoming request
            url = request.url

            # Get the POST data as a dictionary
            post_vars = request.form.to_dict()

            # Retrieve the X-Twilio-Signature header from the request
            signature = request.headers.get('X-Twilio-Signature', '')

            # Validate the request
            if not validator.validate(url, post_vars, signature):
                # If invalid, reject the request
                abort(403)

            # Extract relevant Twilio message fields
            from_number = post_vars['From']
            to_number = post_vars['To']
            message_body = post_vars['Body']
            message_sid = post_vars.get('MessageSid', 'No SID')
            account_sid = post_vars.get('AccountSid', 'No Account SID')
            sms_status = post_vars.get('SmsStatus', 'No Status')
            num_media = post_vars.get('NumMedia', '0')
            twilio_phone_number = client.incoming_phone_numbers.list(phone_number=to_number)
        
            if twilio_phone_number:
                twilio_phone_number_sid = twilio_phone_number[0].sid
            else:
                twilio_phone_number_sid = None
        
            if not twilio_phone_number_sid:
                return 'Unauthorized', 403

            # Log the incoming request details
            current_app.logger.info(f'Incoming SMS: From={from_number}, To={to_number}, Body={message_body}, SID={message_sid}, Account SID={account_sid}, Phone Number SID: {twilio_phone_number_sid}, Status={sms_status}, Media={num_media}')

            # Validate the user and get the corresponding assistant
            user_id, subscription_id = validate_incomming_message(from_number, twilio_phone_number_sid)

            if not user_id or not subscription_id:
                return 'Unauthorized', 403 

            # Log the user validation details
            current_app.logger.info(f'Validated User: User ID={user_id}, Subscription ID={subscription_id}, From Number={from_number}')

            save_sms_history(user_id, subscription_id, message_sid, 'incoming', from_number, to_number, message_body, sms_status)

            user_preferences = UserPreference.query.filter_by(user_id=user_id, subscription_id=subscription_id).first()

            assistant_preferences = AssistantPreference.query.filter_by(user_id=user_id, subscription_id=subscription_id).first()

            message_answers = None
            # Run the asynchronous process_questions_answers function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            message_answers = loop.run_until_complete(process_questions_answers(message_body, user_preferences.user_location_full, user_preferences.user_location_country))

            prompt = build_system_prompt(user_preferences, assistant_preferences, message_answers)

            current_app.logger.info(f'Assistant System Prompt: {prompt}')       

            chat_history = load_sms_history(user_id, subscription_id, order='desc')

            outgoing_message = build_and_send_messages_openai(prompt, history_records=chat_history)  

            current_app.logger.info(f'Assistant Response: {outgoing_message}')

            send_reply(user_id, subscription_id, outgoing_message, from_number, to_number, client)

            return 'OK', 200
        except Exception as e:
            current_app.logger.error(f"Error: {e}")
            return 'Internal Server Error', 500

    
    @app.route('/api/stripe/callback', methods=['POST'])
    def stripe_callback():
        endpoint_secret = current_app.config['STRIPE_ENDPOINT_SECRET']
        payload = request.get_data(as_text=True)
        sig_header = request.headers.get('Stripe-Signature')
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
        except ValueError as e:
            return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400
        except stripe.error.SignatureVerificationError as e:
            return jsonify({'status': 'error', 'message': 'Invalid signature'}), 400

        event_type = event['type']
        data_object = event['data']['object']

        if event_type == 'invoice.payment_succeeded':
            handle_payment_success(data_object)
        elif event_type == 'invoice.payment_failed':
            handle_billing_issue(data_object)
        elif event_type == 'customer.subscription.deleted':
            handle_subscription_cancellation(data_object)

        return jsonify({'status': 'success'}), 200

    
    @sitemap.register_generator
    def index():
        yield 'index_page', {}

    @sitemap.register_generator
    def about():
        yield 'about_page', {}      

    @sitemap.register_generator
    def contact():
        yield 'contact_page', {}     

    @sitemap.register_generator
    def terms():
        yield 'terms_page', {}    

    @sitemap.register_generator
    def privacy():
        yield 'privacy_page', {}    

    @sitemap.register_generator
    def faq():
        yield 'faq_page', {}    
