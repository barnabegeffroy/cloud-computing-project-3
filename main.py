from datetime import datetime
import hashlib
import local_constants
import google.oauth2.id_token
from flask import Flask, render_template, request, redirect, url_for
from google.auth.transport import requests
from google.cloud import datastore, storage

app = Flask(__name__)
datastore_client = datastore.Client()
firebase_request_adapter = requests.Request()


def createUser(email, name, username, bio):
    id = hashlib.md5(email.encode()).hexdigest()
    entity_key = datastore_client.key('User', id)
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


def getUserByClaims(claims):
    id = hashlib.md5(claims['email'].encode()).hexdigest()
    entity_key = datastore_client.key('User', id)
    return datastore_client.get(entity_key)


def getUserById(id):
    entity_key = datastore_client.key('User', id)
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
    feed = None
    message = request.args.get('message')
    status = request.args.get('status')
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUserByClaims(claims)
            if not user_data:
                return redirect('/init_account')
            feed = getFeed(user_data)
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return render_template('index.html', user_data=user_data, feed=feed, message=message, status=status)


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
    return render_template('init_account.html', user_data=claims, init=True, message=message, status=status)


@app.route('/put_user', methods=['POST'])
def putUser():
    id_token = request.cookies.get("token")
    claims = None
    user_data = None
    message = None
    status = None
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUserByClaims(claims)
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
    return redirect(url_for('.root', message=message, status=status))
    # return render_template('index.html', user_data=user_data,, tutorial=True)


@app.route('/login')
def login():
    id_token = request.cookies.get("token")
    if id_token:
        return redirect(url_for('.root', message="You are already logged in", status="success"))
    else:
        return render_template('login.html')


@app.route('/user/<string:id>', methods=['GET'])
def user(id):
    id_token = request.cookies.get("token")
    claims = None
    user_data = None
    user = None
    ownProfile = False
    tweets = None
    message = request.args.get('message')
    status = request.args.get('status')
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUserByClaims(claims)
            if user_data.key.name == id:
                ownProfile = True
                tweets = getLast50Tweets(user_data)
            else:
                user = getUserById(id)
                if user:
                    tweets = getLast50Tweets(user)
                else:
                    return redirect(url_for('.root', message="This user does not exist", status="error"))
            tweets.sort(key=lambda x: x['date'], reverse=True)
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return render_template('user.html', user_data=user_data, user=user, ownProfile=ownProfile, tweets=tweets, message=message, status=status)


def updateUser(user, name, bio):
    user.update({
        'name': name,
        'bio': bio
    })
    datastore_client.put(user)


@app.route('/edit_user', methods=['POST'])
def edit_user():
    id_token = request.cookies.get("token")
    claims = None
    user_data = None
    message = None
    status = None
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUserByClaims(claims)
            updateUser(
                user_data, request.form['name'], request.form['bio-text'])
            message = "Your profile has been updated"
            status = "success"
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        redirect('/login')
    return redirect(url_for('.user', id=user_data.key.name, message=message, status=status))


def addFile(entity, file):
    filename_parts = file.filename.split('.')
    if filename_parts[-1] not in ['jpg', 'jpeg', 'png']:
        return None
    name = filename_parts[0]
    if (len(filename_parts) > 2):
        name_parts = [filename_parts[i]
                      for i in range(len(filename_parts) - 1)]
        ".".join(name_parts)
        name = name_parts

    id = hashlib.md5(
        (name + entity.key.name + str(datetime.today())).encode()).hexdigest()
    file.filename = id + "." + filename_parts[-1]
    storage_client = storage.Client(project=local_constants.PROJECT_NAME)
    bucket = storage_client.bucket(local_constants.PROJECT_STORAGE_BUCKET)
    blob = bucket.blob(file.filename)
    blob.upload_from_file(file)
    return file.filename


def createTweet(user, content, filename):
    today = datetime.today()
    id = hashlib.md5((user.key.name + str(today)).encode()).hexdigest()
    entity_key = datastore_client.key('Tweet', id)
    tweetEntity = datastore.Entity(key=entity_key)
    tweetEntity.update({
        'user': user.key.name,
        'content': content,
        'file': filename,
        'date': today
    })
    tweets = user['tweets']
    tweets.append(id)
    user.update({
        'tweets': tweets,
    })
    transaction = datastore_client.transaction()
    with transaction:
        transaction.put(tweetEntity)
        transaction.put(user)


@app.route('/put_tweet', methods=['POST'])
def putTweet():
    id_token = request.cookies.get("token")
    claims = None
    user_data = None
    message = None
    status = None
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUserByClaims(claims)
            file = request.files['file-name']
            isOk = True
            filename = None
            if file.filename != '':
                filename = addFile(user_data, file)
                isOk = filename != None
            if isOk:
                createTweet(
                    user_data, request.form['tweet-text'], filename)
                message = "Your tweet has been created"
                status = "success"
            else:
                message = 'You should should a picture file (png, jpg, jpeg)'
                status = 'error'
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        redirect('/login')
    return redirect(getLastUrl(request.referrer, message, status))


def getUsers(str):
    print(str)
    query = datastore_client.query(kind='User')
    query.add_filter('username', '=', str)
    return list(query.fetch())


@app.route('/search_user', methods=['GET'])
def searchUser():
    id_token = request.cookies.get("token")
    claims = None
    user_data = None
    message = request.args.get('message')
    status = request.args.get('status')
    result = None
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUserByClaims(claims)
            result = getUsers(request.args.get('search-input'))
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return render_template('search_users.html', user_data=user_data, text=request.args.get('search-input'), result=result,  message=message, status=status)


def getTweets(str):
    query = datastore_client.query(kind='Tweet')
    query.add_filter('content', '=', str)
    result = list(query.fetch())
    result.sort(key=lambda x: x['date'], reverse=True)
    tuples = []
    for tweet in result:
        tuples.append((getUserById(tweet['user']), tweet))
    return tuples


@app.route('/search_tweet', methods=['GET'])
def searchTweet():
    id_token = request.cookies.get("token")
    claims = None
    user_data = None
    message = request.args.get('message')
    status = request.args.get('status')
    result = None
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUserByClaims(claims)
            result = getTweets(request.args.get('search-input'))
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return render_template('search_tweets.html', user_data=user_data, text=request.args.get('search-input'), result=result,  message=message, status=status)


def followUser(user, followingId):
    followingList = user['followings']
    followingList.append(followingId)
    user.update({
        'followings': followingList
    })
    followingUser = getUserById(followingId)
    followerList = followingUser['followers']
    followerList.append(user.key.name)
    followingUser.update({
        'followers': followerList
    })
    transaction = datastore_client.transaction()
    with transaction:
        transaction.put(user)
        transaction.put(followingUser)
    return followingUser['username']


@app.route('/follow', methods=['POST'])
def follow():
    id_token = request.cookies.get("token")
    claims = None
    user_data = None
    message = None
    status = None
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUserByClaims(claims)
            userNameFollowing = followUser(
                user_data, request.form['following-id'])
            message = "You start to follow @" + userNameFollowing
            status = "success"
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return redirect(getLastUrl(request.referrer, message, status))


def unfollowUser(user, followingId):
    followingList = user['followings']
    index = followingList.index(followingId)
    del followingList[index]
    user.update({
        'followings': followingList
    })
    followingUser = getUserById(followingId)
    followerList = followingUser['followers']
    index = followerList.index(user.key.name)
    del followerList[index]
    followingUser.update({
        'followers': followerList
    })
    transaction = datastore_client.transaction()
    with transaction:
        transaction.put(user)
        transaction.put(followingUser)
    return followingUser['username']


@app.route('/unfollow', methods=['POST'])
def unfollow():
    id_token = request.cookies.get("token")
    claims = None
    user_data = None
    message = None
    status = None
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUserByClaims(claims)
            userNameFollowing = unfollowUser(
                user_data, request.form['following-id'])
            message = "You have stopped to follow @" + userNameFollowing
            status = "success"
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return redirect(getLastUrl(request.referrer, message, status))


def getLast50Tweets(user):
    tweetIds = user['tweets'][-50:]
    tweetKeys = []
    for i in range(len(tweetIds)):
        tweetKeys.append(datastore_client.key('Tweet', tweetIds[i]))
    result = datastore_client.get_multi(tweetKeys)
    return result


def getFeed(user):
    followingIds = user['followings']
    followingKeys = []
    for i in range(len(followingIds)):
        followingKeys.append(datastore_client.key('User', followingIds[i]))
    followings = datastore_client.get_multi(followingKeys)
    followings.append(user)
    tweets = []
    for following in followings:
        tweets += getLast50Tweets(following)
    tweets.sort(key=lambda x: x['date'], reverse=True)
    tweets = tweets[:50]
    feed = []
    for tweet in tweets:
        feed.append(
            ([x for x in followings if x.key.name == tweet['user']][0], tweet))
    return feed


def deleteTweet(id, user):
    tweetList = user['tweets']
    entity_key = datastore_client.key('Tweet', id)
    tweet = datastore_client.get(entity_key)
    deleteFileFromStorage(tweet['file'])
    datastore_client.delete(entity_key)
    index = tweetList.index(id)
    del tweetList[index]
    user.update({
        'tweets': tweetList
    })
    datastore_client.put(user)


@app.route('/delete/<string:id>')
def delete(id):
    id_token = request.cookies.get("token")
    claims = None
    user_data = None
    message = None
    status = None
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                id_token, firebase_request_adapter)
            user_data = getUserByClaims(claims)
            deleteTweet(id, user_data)
            message = "Your tweet has been deleted"
            status = "success"
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return redirect(getLastUrl(request.referrer, message, status))


def updateTweet(id, content):
    entity_key = datastore_client.key('Tweet', id)
    tweet = datastore_client.get(entity_key)
    tweet.update({
        'content': content,
    })
    datastore_client.put(tweet)


@app.route('/edit_tweet', methods=['POST'])
def editTweet():
    id_token = request.cookies.get("token")
    message = None
    status = None
    if id_token:
        try:
            updateTweet(request.form['tweet-id'],
                        request.form['tweet-text'])
            message = "Your tweet has been updated"
            status = "success"
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return redirect(getLastUrl(request.referrer, message, status))


def deleteFileFromStorage(filename):
    storage_client = storage.Client(project=local_constants.PROJECT_NAME)
    bucket = storage_client.bucket(local_constants.PROJECT_STORAGE_BUCKET)
    blob = bucket.blob(filename)
    blob.delete()


def deletePicture(id):
    entity_key = datastore_client.key('Tweet', id)
    tweet = datastore_client.get(entity_key)
    deleteFileFromStorage(tweet['file'])
    tweet.update({
        'file': None
    })
    datastore_client.put(tweet)


@app.route('/delete_pic/<string:id>')
def deletePicForm(id):
    id_token = request.cookies.get("token")
    message = None
    status = None
    if id_token:
        try:
            deletePicture(id)
            message = "The picture has been deleted"
            status = "success"
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return redirect(getLastUrl(request.referrer, message, status))


def updatePicture(id, file):
    entity_key = datastore_client.key('Tweet', id)
    tweet = datastore_client.get(entity_key)
    filename = None
    if file.filename != '':
        filename = addFile(tweet, file)
    if not filename:
        return False
    if tweet['file'] != None:
        deleteFileFromStorage(tweet['file'])
    tweet.update({
        'file': filename
    })
    datastore_client.put(tweet)
    return True


@app.route('/edit_pic', methods=['POST'])
def editPic():
    id_token = request.cookies.get("token")
    message = None
    status = None
    if id_token:
        try:
            if updatePicture(request.form['tweet-id'],
                             request.files['file-name']):
                message = "Your picture has been updated"
                status = "success"
            else:
                message = 'You should should a picture file (png, jpg, jpeg)'
                status = 'error'
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return redirect(getLastUrl(request.referrer, message, status))


def getLastUrl(referrer, message, status):
    url = referrer
    join = '?'
    try:
        if '?search' in referrer:
            join = '&'
        i = referrer.index('message=')
        url = referrer[:(i-1)]
    except:
        url = referrer
    str = ''
    if message:
        str = join+'message=' + message.replace(" ", "+") + '&status='+status
    return url+str


@app.errorhandler(404)
def notFound(error):
    return redirect(url_for('.root', message=error, status="error"))


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)
