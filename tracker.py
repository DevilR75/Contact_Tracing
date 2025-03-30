# Khajiyev Amir A00122387,  Dmitriy Maul A00122400 , Samisha Verma A00120599 Saman Thapa Magar A00127870
# Tracker Module: Receives position messages, processes queries, and tracks contacts using RabbitMQ
import pika
import json
import time
from collections import defaultdict

# Queue and exchange names for messaging
QUERY_TOPIC = 'query'                      # Queue for incoming query messages
CONFIG_REQUEST_QUEUE = 'config_request'    # Queue for configuration (e.g., board size) requests
CONFIG_RESPONSE_QUEUE = 'config_response'  # Queue for configuration responses
EXCHANGE_NAME = 'positions'                # Exchange used to broadcast position messages

class Tracker:
    def __init__(self, host, board_size):
        """
        Initialize the Tracker with the given RabbitMQ host and board size.
        Set up the connection, declare the exchange and required queues,
        and initialize data structures for positions and contact events.
        """
        connection_params = pika.ConnectionParameters(host=host)
        self.connection = pika.BlockingConnection(connection_params)
        self.channel = self.connection.channel()

        # Declare the exchange for position messages and bind an anonymous queue to it.
        self.channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type='fanout')
        result = self.channel.queue_declare(queue="", exclusive=False)
        self.position_queue = result.method.queue
        self.channel.queue_bind(exchange=EXCHANGE_NAME, queue=self.position_queue)

        # Declare queues for queries and configuration.
        self.channel.queue_declare(queue=QUERY_TOPIC)
        self.channel.queue_declare(queue=CONFIG_REQUEST_QUEUE)
        self.channel.queue_declare(queue=CONFIG_RESPONSE_QUEUE)

        # Store the full message for each person by person_id.
        self.positions = {}  # e.g., { 1065: {"name": "Bob", "x": 7, "y": 8, ...} }
        # Record contact events: key: person_id, value: list of tuples.
        # Each tuple: (contact's name, contact's person_id, x, y) where the contact occurred.
        self.contacts = defaultdict(list)
        self.board_size = board_size

    def start(self):
        """
        Start consuming messages from the position, query, and configuration queues.
        Register callbacks to handle each type of incoming message.
        """
        self.channel.basic_consume(
            queue=self.position_queue,
            on_message_callback=self.on_position_message,
            auto_ack=True
        )
        self.channel.basic_consume(
            queue=QUERY_TOPIC,
            on_message_callback=self.on_query_message,
            auto_ack=True
        )
        self.channel.basic_consume(
            queue=CONFIG_REQUEST_QUEUE,
            on_message_callback=self.on_config_request,
            auto_ack=True
        )
        print("[Tracker] Started. Waiting for messages...")
        self.channel.start_consuming()

    def on_position_message(self, ch, method, properties, body):
        """
        Process incoming position messages.
        Expected JSON format:
          {
            "name": <str>,
            "person_id": <int>,
            "x": <int>,
            "y": <int>,
            "timestamp": <float>
          }
        Update the current position for the person and record a contact event if
        two persons share the same coordinates.
        """
        try:
            msg = json.loads(body)
            person_id = msg["person_id"]
            x = msg["x"]
            y = msg["y"]
            ts = msg["timestamp"]
        except (json.JSONDecodeError, KeyError):
            print("[Tracker] Invalid 'position' message")
            return

        # Store the full message data for this person.
        self.positions[person_id] = msg

        # Check for contacts with other persons at the same coordinates.
        for other_id, other_msg in self.positions.items():
            if other_id == person_id:
                continue
            ox = other_msg.get("x")
            oy = other_msg.get("y")
            if ox == x and oy == y:
                # Record contact for both persons as (name, id, x, y)
                contact_detail = (other_msg.get("name"), other_id, x, y)
                self.contacts[person_id].append(contact_detail)
                contact_detail_other = (msg.get("name"), person_id, ox, oy)
                self.contacts[other_id].append(contact_detail_other)

    def on_query_message(self, ch, method, properties, body):
        """
        Process a query for a specific person.
        Expected query format (JSON):
          {
            "person_id": <int>
          }
        The response includes:
          - person_id
          - contacts: a list of strings, each formatted as "Name (id:ID) at [x ; y]"
          - position: the current coordinates formatted as "[x ; y]"
        """
        try:
            msg = json.loads(body)
            person_id = msg["person_id"]
        except (json.JSONDecodeError, KeyError):
            print("[Tracker] Invalid 'query' message")
            return

        # Retrieve contact events for the person and format each contact.
        contact_list = self.contacts.get(person_id, [])
        formatted_contacts = []
        for contact in contact_list:
            # Format each contact as "Name (id:ID) at [x ; y]"
            formatted_str = f"{contact[0]} (id:{contact[1]}) at [{contact[2]} ; {contact[3]}]"
            formatted_contacts.append(formatted_str)

        # Get the current position for the person.
        if person_id in self.positions:
            current_msg = self.positions[person_id]
            current_position = f"[{current_msg.get('x')} ; {current_msg.get('y')}]"
        else:
            current_position = "[-1 ; -1]"

        response = {
            "person_id": person_id,
            "contacts": formatted_contacts,
            "position": current_position
        }

        # Send the response to the reply_to queue using the provided correlation_id.
        reply_to = properties.reply_to
        correlation_id = properties.correlation_id
        if reply_to:
            ch.basic_publish(
                exchange='',
                routing_key=reply_to,
                properties=pika.BasicProperties(correlation_id=correlation_id),
                body=json.dumps(response).encode('utf-8')
            )
            print(f"[Tracker] Response for '{person_id}' sent with correlation_id {correlation_id}")
        else:
            print(f"[Tracker] No reply_to specified for query {person_id}")

    def on_config_request(self, ch, method, properties, body):
        """
        Handle configuration requests by responding with the board size.
        """
        response = {
            "board_size": self.board_size
        }
        self.channel.basic_publish(
            exchange='',
            routing_key=CONFIG_RESPONSE_QUEUE,
            body=json.dumps(response).encode('utf-8')
        )
        print("[Tracker] Board size request received. Sent =", self.board_size)

def main():
    """
    Main function to start the Tracker.
    Prompts for the RabbitMQ host and board size, then initializes and starts the Tracker.
    """
    print("=== Starting Tracker ===")
    host = input("Enter RabbitMQ host address [default 'localhost']: ") or "localhost"
    board_size_str = input("Enter board size (N x N) [default 10]: ") or "10"
    board_size = int(board_size_str)

    tracker = Tracker(host, board_size)
    tracker.start()

if __name__ == "__main__":
    main()
