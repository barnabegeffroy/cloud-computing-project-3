from crypt import methods
from datetime import datetime
import hashlib
import google.oauth2.id_token
from flask import Flask, render_template, request, redirect, url_for
from google.auth.transport import requests
from google.cloud import datastore


app = Flask(__name__)
datastore_client = datastore.Client()
firebase_request_adapter = requests.Request()


def createUser(email, name, username, bio):
    entity_key = datastore_client.key('User', email)
    entity = datastore.Entity(key=entity_key)
    entity.update({
        'username': username,
        'name': name,
        'bio': bio,
        'tweets': [],
        'followings': [],
        'followers': []
    })
    datastore_client.put(entity)
    return entity


def getUser(claims):
    entity_key = datastore_client.key('User', claims['email'])
    return datastore_client.get(entity_key)


def getUserByUsername(username):
    query = datastore_client.query(kind='User')
    query.add_filter('username', '=', username)
    result = list(query.fetch())
    if len(result) == 0:
        return None
    else:
        return result[0]


@app.route('/', methods=['GET'])
def root():
    id_token = request.cookies.get("token")
    claims = None
    user_data = None
    message = request.args.get('message')
    status = request.args.get('status')
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUser(claims)
            if not user_data:
                return redirect('/init_account')

        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return render_template('index.html', user_data=user_data, message=message, status=status)


@app.route('/init_account', methods=['GET'])
def initAccount():
    id_token = request.cookies.get("token")
    claims = None
    message = request.args.get('message')
    status = request.args.get('status')
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)

        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        redirect('/login')
    return render_template('create_account.html', user_data=claims, message=message, status=status)


@app.route('/create_account', methods=['POST'])
def createAccount():
    id_token = request.cookies.get("token")
    claims = None
    user_data = None
    message = None
    status = None
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUser(claims)
            if user_data:
                return redirect('/')
            name = request.form['name']
            username = request.form['username']
            bio = request.form['bio-text']
            if getUserByUsername(username):
                return redirect(url_for('.initAccount', message="This username is already owned by someone", status="error"))

            user_data = createUser(
                claims['email'], name, username, bio)
            message = "Your account has been created"
            status = "success"
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        redirect('/login')
    return render_template('index.html', user_data=user_data, message=message, status=status, tutorial=True)


@app.route('/login')
def login():
    id_token = request.cookies.get("token")
    if id_token:
        return redirect(url_for('.root', message="You are already logged in", status="success"))
    else:
        return render_template('login.html')


@app.route('/user', methods=['GET'])
def user():
    id_token = request.cookies.get("token")
    claims = None
    user_data = None
    message = request.args.get('message')
    status = request.args.get('status')
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUser(claims)
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return render_template('user.html', user_data=user_data, message=message, status=status)


@app.errorhandler(404)
def notFound(error):
    return redirect(url_for('.root', message=error, status="error"))


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)
