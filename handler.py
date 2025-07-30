import json
import os
import logging
import africastalking
from urllib.parse import parse_qs
import boto3

# Initialize logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS DynamoDB client
dynamodb = boto3.resource('dynamodb')
users_table_name = os.environ.get('USERS_TABLE')
if not users_table_name:
    logger.error("USERS_TABLE environment variable not set. DynamoDB operations will fail.")
    users_table = None
else:
    users_table = dynamodb.Table(users_table_name)
    logger.info(f"DynamoDB table '{users_table_name}' initialized.")


# Initialize Africa's Talking SDK
AT_USERNAME = os.environ.get('AFRICASTALKING_USERNAME')
AT_API_KEY = os.environ.get('AFRICASTALKING_API_KEY')

if AT_USERNAME and AT_API_KEY:
    try:
        africastalking.initialize(AT_USERNAME, AT_API_KEY)
        sms_service = africastalking.SMS
        logger.info("Africa's Talking SDK initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing Africa's Talking SDK: {e}")
        sms_service = None
else:
    logger.warning("AFRICASTALKING_USERNAME or AFRICASTALKING_API_KEY not set. Cannot send SMS.")
    sms_service = None

# --- GAME DATA DEFINITIONS (KEEP AS IS) ---
GAME_DATA = {
    "hustle_intro": {
        "message": "Welcome to Choose Your Hustle! Reach KES 10,000 net worth. To start, what's your first move?",
        "options": [
            "1. Look for a formal job.",
            "2. Start a small side hustle.",
            "3. Try your luck with a quick crypto trade."
        ],
        "next_state": "hustle_q1" # <-- It has 'next_state', NOT 'outcomes'
    },
    "hustle_q1": {
        "message": "A potential investor hears about your idea and wants to invest. He offers a very high amount because he is very intrigued. He is impatient and wants you to go all in or leave it.",
        "options": [
            "1. Take it, no questions asked (Big risk, big reward).",
            "2. Ask for a meeting to review terms (Cautious).",
            "3. Reject, too good to be true (Safe)."
        ],
        "outcomes": {
            "1": {"effect": {"net_worth": 5000}, "message": "You blindly took the deal! It paid off big time! (+KES 5000)", "next_state": "hustle_q2"},
            "2": {"effect": {"net_worth": -1000}, "message": "He got impatient and pulled out. You wasted time. (-KES 1000)", "next_state": "hustle_q2"},
            "3": {"effect": {"net_worth": 0}, "message": "You dodged a bullet, but also missed an opportunity. (No change)", "next_state": "hustle_q2"}
        }
    },
    "hustle_q2": {
        "message": "Your cousin asks to borrow KES 2000 for an emergency. They promise to pay back next week.",
        "options": [
            "1. Lend them the money (Goodwill).",
            "2. Lend half, keep half (Cautious).",
            "3. Say no, you need the money (Self-preservation)."
        ],
        "outcomes": {
            "1": {"effect": {"net_worth": -2000, "random_event": "ghosted"}, "message": "You lent the money. Fingers crossed!", "next_state": None},
            "2": {"effect": {"net_worth": -1000}, "message": "You lent half. Better safe than sorry.", "next_state": "hustle_q3"},
            "3": {"effect": {"net_worth": 0}, "message": "You kept your funds. Wise choice.", "next_state": "hustle_q3"}
        }
    },
    "hustle_q3": {
        "message": "A new tech trend emerges: AI-powered personalized fashion. Do you pivot?",
        "options": [
            "1. Go all-in, invest heavily in AI tools (High risk, potential high reward).",
            "2. Research and learn first, make small changes (Calculated risk).",
            "3. Stick to your original plan, avoid fads (Conservative)."
        ],
        "outcomes": {
            "1": {"effect": {"net_worth": 3000, "random_event": "ai_boom_bust"}, "message": "You bet big on AI fashion!", "next_state": None},
            "2": {"effect": {"net_worth": 1000}, "message": "Your careful pivot yields steady growth. (+KES 1000)", "next_state": "hustle_q4"},
            "3": {"effect": {"net_worth": -500}, "message": "You missed out on new opportunities. (-KES 500)", "next_state": "hustle_q4"}
        }
    },
    "hustle_q4": {
        "message": "Your biggest competitor offers to buy your side hustle for KES 8,000. Do you sell or keep building?",
        "options": [
            "1. Sell now, take the guaranteed money.",
            "2. Reject, you believe it's worth more.",
            "3. Counter-offer for KES 12,000."
        ],
        "outcomes": {
            "1": {"effect": {"net_worth": 8000}, "message": "You sold your hustle! A solid exit. (+KES 8000)", "next_state": "check_win"},
            "2": {"effect": {"net_worth": -1500, "random_event": "market_crash"}, "message": "You hold on, hoping for more. (-KES 1500)", "next_state": None},
            "3": {"effect": {"net_worth": 0, "random_event": "negotiation_fail"}, "message": "Your counter-offer was too high. They walked away.", "next_state": None}
        }
    },
    "death_scam": "You joined a WhatsApp forex group. Now you’re broke and blocked. 💀 Reply RESTART to start again.",
    "death_starved": "You thought wild berries were a meal. They were poison. You now rest with the frogs. 💀 Reply RESTART to start again.",
    "win_hustle": "Congratulations! You hustled your way to KES 10,000! You're a true urban survivor! 🎉 Reply RESTART to play again.",
    "default_death": "You made a fatal error. Your hustle ended here. 💀 Reply RESTART to start again."
}

RANDOM_EVENTS = {
    "ghosted": {
        "message": "Oh no! Your cousin ghosted you! That KES 2000 is gone forever. (-KES 2000)",
        "effect": {"net_worth": -2000},
        "next_state": "hustle_q3"
    },
    "ponzi": {
        "message": "You invested in a 'guaranteed' crypto scheme. It was a Ponzi. You lost everything! (-ALL)",
        "effect": {"net_worth": "die"},
        "next_state": None
    },
    "ai_boom_bust": {
        "message": "The AI bubble burst! You lost half your net worth but learned a valuable lesson. (-HALF)",
        "effect": {"net_worth_percentage": -0.5},
        "next_state": "hustle_q4"
    },
    "market_crash": {
        "message": "The market crashed right after you rejected the offer! Your hustle's value plummeted. (-ALL)",
        "effect": {"net_worth": "die"},
        "next_state": None
    },
    "negotiation_fail": {
        "message": "Your reputation for greed spread. No one wants to do business with you. (-1000)",
        "effect": {"net_worth": -1000},
        "next_state": "hustle_q4"
    }
}

HUSTLE_GOAL = 10000

# Helper function to send SMS reply
def send_sms_reply(sms_instance, recipient_number, message_text):
    if sms_instance:
        try:
            logger.info(f"*** SIMULATED SMS TO {recipient_number}: ***\n{message_text}\n***********************************")
            # Use the original recipient_number (with '+') for Africa's Talking
            response = sms_instance.send(message_text, [recipient_number])
            logger.info(f"SMS sent successfully to {recipient_number}: {response}")
        except Exception as e:
            logger.error(f"Failed to send SMS to {recipient_number}: {e}")
    else:
        logger.error("Africa's Talking SDK not initialized. Cannot send reply.")

# --- DynamoDB Helper Functions ---
def get_user_state(db_phone_number): # Changed argument name to avoid confusion
    if not users_table:
        logger.error("DynamoDB table not initialized.")
        return None
    try:
        response = users_table.get_item(Key={'phoneNumber': db_phone_number})
        item = response.get('Item')
        if item:
            # DynamoDB stores numbers as Decimal, convert to int/float
            for key in ['net_worth', 'days_survived']:
                if key in item:
                    item[key] = int(item[key]) # Convert Decimal to int
            
            # Convert empty strings from DB to None for game state
            if item.get('game') == '': item['game'] = None
            if item.get('current_q') == '': item['current_q'] = None

            return item
        return None
    except Exception as e:
        logger.error(f"Error getting user state for {db_phone_number}: {e}")
        return None

def save_user_state(user_state):
    if not users_table:
        logger.error("DynamoDB table not initialized. Cannot save state.")
        return False
    try:
        # DynamoDB doesn't like None for string attributes, use empty string instead
        item_to_save = user_state.copy()
        if item_to_save.get('game') is None: item_to_save['game'] = ''
        if item_to_save.get('current_q') is None: item_to_save['current_q'] = ''

        users_table.put_item(Item=item_to_save)
        logger.info(f"User state saved for {user_state['phoneNumber']}")
        return True
    except Exception as e:
        logger.error(f"Error saving user state for {user_state['phoneNumber']}: {e}")
        return False

# --- NEW HELPER FUNCTION for applying outcomes and getting message ---
def apply_outcome_and_get_message(outcome, user_state):
    reply_msg = outcome["message"]
    next_q_key_after_outcome = outcome.get("next_state")

    # Apply effects (net_worth change or 'die' command)
    if "net_worth" in outcome["effect"]:
        if outcome["effect"]["net_worth"] == "die":
            reply_msg = GAME_DATA["default_death"]
            user_state["status"] = "dead"
            user_state["game"] = None
            user_state["current_q"] = None
        else:
            user_state["net_worth"] += outcome["effect"]["net_worth"]
    elif "net_worth_percentage" in outcome["effect"]:
        user_state["net_worth"] += int(user_state["net_worth"] * outcome["effect"]["net_worth_percentage"])

    # Handle random events
    if "random_event" in outcome["effect"]:
        event_key = outcome["effect"]["random_event"]
        if event_key in RANDOM_EVENTS:
            random_event_data = RANDOM_EVENTS[event_key]
            reply_msg += f"\n{random_event_data['message']}"
            if "net_worth" in random_event_data["effect"]:
                if random_event_data["effect"]["net_worth"] == "die":
                    reply_msg = GAME_DATA["default_death"]
                    user_state["status"] = "dead"
                    user_state["game"] = None
                    user_state["current_q"] = None
                else:
                    user_state["net_worth"] += random_event_data["effect"]["net_worth"]
            elif "net_worth_percentage" in random_event_data["effect"]:
                user_state["net_worth"] += int(user_state["net_worth"] * random_event_data["effect"]["net_worth_percentage"])
            
            # Random events can override next state
            next_q_key_after_outcome = random_event_data.get("next_state", next_q_key_after_outcome)
    
    # Ensure net worth doesn't go negative if not a death state
    if user_state["status"] == "alive" and user_state["net_worth"] < 0:
        user_state["net_worth"] = 0

    # Check for WIN condition
    if user_state["status"] == "alive" and user_state["net_worth"] >= HUSTLE_GOAL:
        reply_msg += f"\n{GAME_DATA['win_hustle']}\nCurrent Net Worth: KES {user_state['net_worth']}"
        user_state["status"] = "dead"
        user_state["game"] = None
        user_state["current_q"] = None
    elif user_state["status"] == "alive": # If still alive, set next question
        user_state["current_q"] = next_q_key_after_outcome if next_q_key_after_outcome else "hustle_intro" # Default to intro if no specific next state
    
    return reply_msg, user_state


def inbound_sms_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    # Store the original `from` number (with '+')
    original_from_number = None
    # This will be the cleaned number for DynamoDB
    db_phone_number = None
    text_message = None

    try:
        if isinstance(event.get('body'), str):
            body_params = parse_qs(event['body'])
            original_from_number = body_params.get('from', [None])[0]
            text_message = body_params.get('text', [None])[0].strip().upper()
            link_id = body_params.get('linkId', [None])[0]
        else:
            original_from_number = event.get('from')
            text_message = event.get('text').strip().upper()
            link_id = event.get('linkId')

        if original_from_number:
            # Create a DB-friendly phone number (without '+')
            db_phone_number = original_from_number.replace('+', '')

    except Exception as e:
        logger.error(f"Error parsing incoming SMS webhook body: {e}")
        return {
            'statusCode': 400,
            'body': json.dumps({'message': 'Bad Request: Could not parse SMS body'})
        }

    if not original_from_number or not text_message:
        logger.warning("Missing 'from' or 'text' in incoming SMS event.")
        return {
            'statusCode': 400,
            'body': json.dumps({'message': 'Bad Request: Missing SMS parameters'})
        }

    logger.info(f"Incoming SMS from: {original_from_number}, Message: {text_message}")

    reply_message = ""

    # --- Retrieve User State from DynamoDB ---
    # Use db_phone_number for DynamoDB operations
    current_user_state = get_user_state(db_phone_number)
    if current_user_state is None:
        # Initialize new user state if not found
        current_user_state = {
            "phoneNumber": db_phone_number, # Primary key for DynamoDB (without '+')
            "game": None,
            "status": "alive",
            "net_worth": 0,
            "days_survived": 0,
            "current_q": None
        }
        logger.info(f"New user state initialized for {db_phone_number}")
    else:
        logger.info(f"Loaded user state for {db_phone_number}: {current_user_state}")


    # --- Handle RESTART command ---
    if text_message == "RESTART":
        current_user_state = {
            "phoneNumber": db_phone_number, # Keep phone number for DB
            "game": None,
            "status": "alive",
            "net_worth": 0,
            "days_survived": 0,
            "current_q": None
        }
        reply_message = "Welcome back! What game do you want to play?\n1. Choose Your Hustle\n2. Pick Up or Perish"
        save_user_state(current_user_state) # Save state to DB
        send_sms_reply(sms_service, original_from_number, reply_message) # Use original_from_number here
        return { 'statusCode': 200, 'body': json.dumps({'message': 'Game restarted.'}) }

    # --- Initial Game Selection ---
    if current_user_state["game"] is None:
        if text_message == "1" or text_message == "CHOOSE YOUR HUSTLE" or text_message == "HUSTLE":
            current_user_state["game"] = "hustle"
            current_user_state["current_q"] = "hustle_intro" # Set to intro state
            intro_data = GAME_DATA["hustle_intro"]
            reply_message = intro_data["message"] + "\n" + "\n".join(intro_data["options"])
            save_user_state(current_user_state) # Save state to DB
        elif text_message == "2" or text_message == "PICK UP OR PERISH" or text_message == "PERISH":
            reply_message = "Pick Up or Perish is not ready yet. Try Choose Your Hustle (reply 1)."
        else:
            reply_message = "Welcome! What game do you want to play?\n1. Choose Your Hustle\n2. Pick Up or Perish"
        send_sms_reply(sms_service, original_from_number, reply_message)
        # IMPORTANT: Return immediately after game selection to prevent falling into game logic below
        return { 'statusCode': 200, 'body': json.dumps({'message': 'Game selection handled.'}) }

    # --- Handle In-Game Logic (Hustle) ---
    # This block is entered if current_user_state["game"] is NOT None (i.e., a game is in progress)
    if current_user_state["game"] == "hustle" and current_user_state["status"] == "alive":
        current_q_key = current_user_state["current_q"]
        current_q_data = GAME_DATA.get(current_q_key)

        # Handle 'hustle_intro' specifically, as it's a prompt for the first real choice
        if current_q_key == "hustle_intro":
            if text_message in ["1", "2", "3"]:
                # User is making their first choice after the intro, this choice applies to hustle_q1
                # Update current_q to hustle_q1 for the *next* round of interaction.
                # The state is saved immediately after this part of the logic handles the input.
                current_user_state["current_q"] = GAME_DATA["hustle_intro"]["next_state"] # Should be "hustle_q1"
                
                # Now, process this input as if it were for hustle_q1
                # Temporarily get hustle_q1 data for processing the outcome of this turn
                processing_q_data = GAME_DATA.get(GAME_DATA["hustle_intro"]["next_state"])
                if not processing_q_data or "outcomes" not in processing_q_data:
                    reply_message = "Error: Game setup for hustle_q1 is incorrect. Reply RESTART."
                    current_user_state["status"] = "dead"
                    current_user_state["game"] = None
                    current_user_state["current_q"] = None
                else:
                    outcome = processing_q_data["outcomes"].get(text_message)
                    if outcome:
                        # Apply effects and determine next state based on hustle_q1's outcome
                        reply_message, current_user_state = apply_outcome_and_get_message(outcome, current_user_state)
                        
                        # After applying outcome, prepare the message for the *new* current_q
                        if current_user_state["status"] == "alive":
                             next_q_after_choice = GAME_DATA.get(current_user_state["current_q"])
                             if next_q_after_choice and "options" in next_q_after_choice:
                                reply_message += f"\n\nCurrent Net Worth: KES {current_user_state['net_worth']}\n"
                                reply_message += next_q_after_choice["message"] + "\n"
                                reply_message += "\n".join(next_q_after_choice["options"])
                             elif current_user_state["current_q"] == "check_win":
                                 # Win condition already handled within apply_outcome_and_get_message if net_worth >= GOAL
                                 pass
                             else: # Unexpected end of flow (e.g., ran out of questions without explicit win/loss)
                                 reply_message += "\nUnexpected game end. Reply RESTART to start again."
                                 current_user_state["status"] = "dead"
                                 current_user_state["game"] = None
                                 current_user_state["current_q"] = None

                    else: # Invalid option for hustle_q1 (when current_q was hustle_intro)
                        reply_message = "Invalid choice. Please reply with 1, 2, or 3 for your first move."
                        intro_data = GAME_DATA["hustle_intro"] # Show intro options again
                        reply_message += "\n" + "\n".join(intro_data["options"])
            else: # Input not 1,2,3 for hustle_intro
                reply_message = "Please choose a valid option (1, 2, or 3) to start your hustle."
                intro_data = GAME_DATA["hustle_intro"] # Show intro options again
                reply_message += "\n" + "\n".join(intro_data["options"])

            save_user_state(current_user_state)
            send_sms_reply(sms_service, original_from_number, reply_message)
            return { 'statusCode': 200, 'body': json.dumps({'message': 'Hustle intro choice processed.'}) }

        # --- General Game Question Logic (for states with "outcomes") ---
        # This block is reached if current_q_key is NOT 'hustle_intro' (e.g., 'hustle_q1', 'hustle_q2' etc.)
        if not current_q_data or "outcomes" not in current_q_data:
            reply_message = "Error: Invalid game state (missing outcomes for current question). Reply RESTART to begin anew."
            current_user_state["status"] = "dead"
            current_user_state["game"] = None
            current_user_state["current_q"] = None
            save_user_state(current_user_state)
            send_sms_reply(sms_service, original_from_number, reply_message)
            return { 'statusCode': 200, 'body': json.dumps({'message': 'Error in game state.'}) }

        if text_message in ["1", "2", "3"]:
            chosen_option = text_message
            outcome = current_q_data["outcomes"].get(chosen_option)

            if outcome:
                reply_message, current_user_state = apply_outcome_and_get_message(outcome, current_user_state)
                
                # After applying outcome, prepare the message for the *new* current_q
                if current_user_state["status"] == "alive": # If still alive after outcome
                    next_q_data = GAME_DATA.get(current_user_state["current_q"])
                    if next_q_data and "options" in next_q_data:
                        reply_message += f"\n\nCurrent Net Worth: KES {current_user_state['net_worth']}\n"
                        reply_message += next_q_data["message"] + "\n"
                        reply_message += "\n".join(next_q_data["options"])
                    elif current_user_state["current_q"] == "check_win":
                        # Win condition already handled within apply_outcome_and_get_message if net_worth >= GOAL
                        pass
                    else: # Unexpected end of flow (e.g., ran out of questions without explicit win/loss)
                        reply_message += "\nUnexpected game end. Reply RESTART to start again."
                        current_user_state["status"] = "dead"
                        current_user_state["game"] = None
                        current_user_state["current_q"] = None
                
                save_user_state(current_user_state)

            else: # Invalid option chosen for current_q_key
                reply_message = "Invalid choice. Please reply with 1, 2, or 3."
                current_q = GAME_DATA.get(current_q_key)
                if current_q and "options" in current_q:
                     reply_message += "\n" + "\n".join(current_q["options"])
                else:
                     reply_message += "\nReply RESTART to begin anew."

        else: # Not a recognized command or choice for in-game
            reply_message = "I don't understand that. Please choose an option (1, 2, 3) or reply RESTART."
            current_q = GAME_DATA.get(current_q_key)
            if current_q and "options" in current_q:
                 reply_message += "\n" + "\n".join(current_q["options"])


    send_sms_reply(sms_service, original_from_number, reply_message)
    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'SMS received and processed successfully!'})
    }