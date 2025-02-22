import flask
import config
import json
import logger
import sys
import io
import traceback
import contextlib
import urllib3
import time
from huckle import cli, stdin
from flask import Flask, render_template, send_file, jsonify, Response, redirect, url_for, request
import subprocess
import ast

logging = logger.Logger()
logging.setLevel(logger.INFO)

app = None


def get_chat_list():
    try:
        chunks = cli("hai ls --json")
        json_string = ""
        for dest, chunk in chunks:
            if dest == 'stdout':
                json_string += chunk.decode()
        chats = json.loads(json_string)
        # Sort the list with most recent dates first
        sorted_chats = sorted(chats, key=lambda x: x['update_time'], reverse=True)
        return sorted_chats
    except Exception as error:
        logging.error(f"Error getting chat list: {error}")
        return []

def parse_context(context_str):
    try:
        context_data = json.loads(context_str)
        return {
            'messages': context_data.get('messages', []),
            'name': context_data.get('name', ''),
            'title': context_data.get('title', '')
        }
    except json.JSONDecodeError as e:
        logging.error(f"Error parsing context JSON: {e}")
        return {'messages': [], 'name': '', 'title': ''}

def webapp():
    app = Flask(__name__)

    @app.route('/')
    def index():
        try:
            # Get the current context
            chunks = cli("hai context --json")
            context_str = ""
            for dest, chunk in chunks:
                if dest == 'stdout':
                    context_str += chunk.decode()

            # Get chat list for sidebar
            chats = get_chat_list()

            # Get model in use
            chunks = cli(f"hai model --json")
            model = ""
            for dest, chunk in chunks:  # Now unpacking tuple of (dest, chunk)
                if dest == 'stdout':
                    model += chunk.decode()

            # Convert to a python list
            model = ast.literal_eval(model)[0]

            # Get models list
            chunks = cli(f"hai model ls --json")
            models = ""
            for dest, chunk in chunks:  # Now unpacking tuple of (dest, chunk)
                if dest == 'stdout':
                    models += chunk.decode()

            # Convert to a python list
            models = ast.literal_eval(models)

            # Parse the context into structured data
            context_data = parse_context(context_str)

            return render_template('index.html',
                                    messages=context_data['messages'],
                                    name=context_data['name'],
                                    title=context_data['title'],
                                    chats=chats,
                                    model=model,
                                    models=models)
        except Exception as error:
            logging.error(traceback.format_exc())
            return render_template('index.html',
                                    messages=[],
                                    name='',
                                    title='',
                                    chats=[],
                                    model=None,
                                    models=[])

    @app.route('/chat_history')
    def chat_history():
        try:
            # Get chat list for sidebar
            chats = get_chat_list()

            # Get model in use
            chunks = cli(f"hai model --json")
            model = ""
            for dest, chunk in chunks:  # Now unpacking tuple of (dest, chunk)
                if dest == 'stdout':
                    model += chunk.decode()

            # Convert to a python list
            model = ast.literal_eval(model)[0]

            # Get models list
            chunks = cli(f"hai model ls --json")
            models = ""
            for dest, chunk in chunks:  # Now unpacking tuple of (dest, chunk)
                if dest == 'stdout':
                    models += chunk.decode()

            # Convert to a python list
            models = ast.literal_eval(models)

            return render_template('chat_history.html', chats=chats,
                                    model=model,
                                    models=models)
        except Exception as error:
            logging.error(traceback.format_exc())
        return render_template('chat_history.html', chats=[],
                                model=None,
                                models=[])

    # We select and set a chat context
    @app.route('/context/<context_id>')
    def navigate_context(context_id):
        try:
            logging.info("Switching to context_id " + context_id)

            chunks = cli(f"hai set {context_id}")
            for dest, chunk in chunks:
                pass

            return redirect(url_for('index'))
        except Exception as error:
            logging.error(f"Context switch failed: {error}")
            logging.error(traceback.format_exc())
            return redirect(url_for('index'))

    # We delete a chat context with hai rm
    @app.route('/context/<context_id>', methods=['POST'])
    def delete_context(context_id):
        try:
            logging.info("Removing context_id " + context_id)

            chunks = cli(f"hai rm {context_id}")
            for dest, chunk in chunks:
                pass

            return redirect(url_for('index'))
        except Exception as error:
            logging.error(f"Context deletion failed: {error}")
            logging.error(traceback.format_exc())
            return redirect(url_for('index'))

    # We stream chat data to hai
    @app.route('/chat', methods=['POST'])
    def chat():
        try:
            message = request.form.get('message')
            logging.info("Sending message to selected model...")
            stream = io.BytesIO(message.encode('utf-8'))

            with stdin(stream):
                chunks = cli(f"hai")
                for dest, chunk in chunks:
                    pass

            return redirect(url_for('index'))
        except Exception as error:
            logging.error(f"Context switch failed: {error}")
            logging.error(traceback.format_exc())
            return redirect(url_for('index'))

    # We set the model with hai model set
    @app.route('/set_model', methods=['POST'])
    def set_model():
        try:
            model = request.form.get('model')
            logging.info(f"Setting model to {model}")

            chunks = cli(f"hai model set {model}")
            for dest, chunk in chunks:
                pass

            return redirect(url_for('index'))
        except Exception as error:
            logging.error(f"Model switch failed: {error}")
            logging.error(traceback.format_exc())
            return redirect(url_for('index'))

    # We create a new hai chat context with hai new
    @app.route('/new_chat', methods=['POST'])
    def new_chat():
        try:
            chunks = cli("hai new")
            for dest, chunk in chunks:
                pass

            return redirect(url_for('index'))
        except Exception as error:
            logging.error(f"New chat creation failed: {error}")
            logging.error(traceback.format_exc())
            return redirect(url_for('index'))

    @app.route('/manifest.json')
    def serve_manifest():
        return app.send_static_file('manifest.json')

    return app

app = webapp()
