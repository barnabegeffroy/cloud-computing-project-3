from datetime import datetime
import hashlib
import local_constants
import google.oauth2.id_token
from flask import Flask, render_template, request, redirect, url_for
from google.auth.transport import requests
from google.cloud import datastore, storage

app = Flask(__name__)
datastoreClient = datastore.Client()
firebaseRequestAdapter = requests.Request()


def createUser(email, name, username, bio):
    id = hashlib.md5(email.encode()).hexdigest()
    entity = datastore.Entity(key=datastoreClient.key('User', id))
    entity.update({
        'username': username,
        'name': name,
        'bio': bio,
        'tweets': [],
        'followings': [],
        'followers': []
    })
    datastoreClient.put(entity)
    return entity


def getUserByClaims(claims):
    id = hashlib.md5(claims['email'].encode()).hexdigest()
    return datastoreClient.get(datastoreClient.key('User', id))


def getUserById(id):
    return datastoreClient.get(datastoreClient.key('User', id))


def getUserByUsername(username):
    query = datastoreClient.query(kind='User')
    query.add_filter('username', '=', username)
    result = list(query.fetch())
    if len(result) == 0:
        return None
    else:
        return result[0]


@app.route('/', methods=['GET'])
def root():
    idToken = request.cookies.get("token")
    claims = None
    userData = None
    feed = None
    message = request.args.get('message')
    status = request.args.get('status')
    if idToken:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                idToken, firebaseRequestAdapter)
            userData = getUserByClaims(claims)
            if not userData:
                return redirect('/init_account')
            feed = getFeed(userData)
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return render_template('index.html', user_data=userData, feed=feed, message=message, status=status)


@app.route('/init_account', methods=['GET'])
def initAccount():
    idToken = request.cookies.get("token")
    claims = None
    message = request.args.get('message')
    status = request.args.get('status')
    if idToken:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                idToken, firebaseRequestAdapter)

        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        redirect('/login')
    return render_template('init_account.html', user_data=claims, init=True, message=message, status=status)


@app.route('/put_user', methods=['POST'])
def putUser():
    idToken = request.cookies.get("token")
    claims = None
    userData = None
    message = None
    status = None
    if idToken:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                idToken, firebaseRequestAdapter)
            userData = getUserByClaims(claims)
            if userData:
                return redirect('/')
            name = request.form['name']
            username = request.form['username']
            bio = request.form['bio-text']
            if getUserByUsername(username):
                return redirect(url_for('.initAccount', message="This username is already owned by someone", status="error"))

            userData = createUser(
                claims['email'], name, username, bio)
            message = "Your account has been created"
            status = "success"
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        redirect('/login')
    return redirect(url_for('.root', message=message, status=status))


@app.route('/login')
def login():
    idToken = request.cookies.get("token")
    if idToken:
        return redirect(url_for('.root', message="You are already logged in", status="success"))
    else:
        return render_template('login.html')


@app.route('/user/<string:id>', methods=['GET'])
def user(id):
    idToken = request.cookies.get("token")
    claims = None
    userData = None
    user = None
    ownProfile = False
    tweets = None
    message = request.args.get('message')
    status = request.args.get('status')
    if idToken:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                idToken, firebaseRequestAdapter)
            userData = getUserByClaims(claims)
            if userData.key.name == id:
                ownProfile = True
                tweets = getLast50Tweets(userData)
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
    return render_template('user.html', user_data=userData, user=user, ownProfile=ownProfile, tweets=tweets, message=message, status=status)


def updateUser(user, name, bio):
    user.update({
        'name': name,
        'bio': bio
    })
    datastoreClient.put(user)


@app.route('/edit_user', methods=['POST'])
def editUser():
    idToken = request.cookies.get("token")
    claims = None
    userData = None
    message = None
    status = None
    if idToken:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                idToken, firebaseRequestAdapter)
            userData = getUserByClaims(claims)
            updateUser(
                userData, request.form['name'], request.form['bio-text'])
            message = "Your profile has been updated"
            status = "success"
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        redirect('/login')
    return redirect(url_for('.user', id=userData.key.name, message=message, status=status))


def addFileToStorage(entity, file):
    # checking if the file is a picture
    filenameParts = file.filename.split('.')
    if filenameParts[-1] not in ['jpg', 'jpeg', 'png']:
        return None
    # get the name of the file without extension
    name = filenameParts[0]
    if (len(filenameParts) > 2):
        nameParts = [filenameParts[i]
                     for i in range(len(filenameParts) - 1)]
        ".".join(nameParts)
        name = nameParts
    # create a unique filename with the name and the entity's id (user or tweet) and the date
    id = hashlib.md5(
        (name + entity.key.name + str(datetime.today())).encode()).hexdigest()
    # rename the file
    file.filename = id + "." + filenameParts[-1]
    # add it to the data storage
    storageClient = storage.Client(project=local_constants.PROJECT_NAME)
    bucket = storageClient.bucket(local_constants.PROJECT_STORAGE_BUCKET)
    blob = bucket.blob(file.filename)
    blob.upload_from_file(file)
    return file.filename


def createTweet(user, content, filename):
    # creates the tweet
    today = datetime.today()
    id = hashlib.md5((user.key.name + str(today)).encode()).hexdigest()
    tweetEntity = datastore.Entity(key=datastoreClient.key('Tweet', id))
    tweetEntity.update({
        'user': user.key.name,
        'content': content,
        'file': filename,
        'date': today
    })
    # update user tweet list
    tweets = user['tweets']
    tweets.append(id)
    user.update({
        'tweets': tweets,
    })
    # put in datastore
    transaction = datastoreClient.transaction()
    with transaction:
        transaction.put(tweetEntity)
        transaction.put(user)


@app.route('/put_tweet', methods=['POST'])
def putTweet():
    idToken = request.cookies.get("token")
    claims = None
    userData = None
    message = None
    status = None
    if idToken:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                idToken, firebaseRequestAdapter)
            userData = getUserByClaims(claims)
            file = request.files['file-name']
            fileIsOk = True
            if file.filename != '':
                filename = addFileToStorage(userData, file)
                fileIsOk = filename != None
            else:
                filename = None
            if fileIsOk:
                createTweet(
                    userData, request.form['tweet-text'], filename)
                message = "Your tweet has been created"
                status = "success"
            else:
                message = 'You should choose a picture file (png, jpg, jpeg)'
                status = 'error'
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        redirect('/login')
    return redirect(getLastUrl(request.referrer, message, status))


def getUsers(str):
    query = datastoreClient.query(kind='User')
    query.add_filter('username', '=', str)
    return list(query.fetch())


@app.route('/search_user', methods=['GET'])
def searchUser():
    idToken = request.cookies.get("token")
    claims = None
    userData = None
    message = request.args.get('message')
    status = request.args.get('status')
    result = None
    if idToken:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                idToken, firebaseRequestAdapter)
            userData = getUserByClaims(claims)
            result = getUsers(request.args.get('search-input'))
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return render_template('search_users.html', user_data=userData, text=request.args.get('search-input'), result=result,  message=message, status=status)


def getTweets(str):
    query = datastoreClient.query(kind='Tweet')
    query.add_filter('content', '=', str)
    result = list(query.fetch())
    result.sort(key=lambda x: x['date'], reverse=True)
    tuples = []
    for tweet in result:
        tuples.append((getUserById(tweet['user']), tweet))
    return tuples


@app.route('/search_tweet', methods=['GET'])
def searchTweet():
    idToken = request.cookies.get("token")
    claims = None
    userData = None
    message = request.args.get('message')
    status = request.args.get('status')
    result = None
    if idToken:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                idToken, firebaseRequestAdapter)
            userData = getUserByClaims(claims)
            result = getTweets(request.args.get('search-input'))
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return render_template('search_tweets.html', user_data=userData, text=request.args.get('search-input'), result=result,  message=message, status=status)


def followUser(user, followingId):
    # update user following list
    followingList = user['followings']
    followingList.append(followingId)
    user.update({
        'followings': followingList
    })
    # update following user its follower list
    followingUser = getUserById(followingId)
    followerList = followingUser['followers']
    followerList.append(user.key.name)
    followingUser.update({
        'followers': followerList
    })
    # put in the datastore
    transaction = datastoreClient.transaction()
    with transaction:
        transaction.put(user)
        transaction.put(followingUser)
    return followingUser['username']


@app.route('/follow', methods=['POST'])
def follow():
    idToken = request.cookies.get("token")
    claims = None
    userData = None
    message = None
    status = None
    if idToken:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                idToken, firebaseRequestAdapter)
            userData = getUserByClaims(claims)
            userNameFollowing = followUser(
                userData, request.form['following-id'])
            message = "You start to follow @" + userNameFollowing
            status = "success"
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return redirect(getLastUrl(request.referrer, message, status))


def unfollowUser(user, followingId):
    # update user following list
    followingList = user['followings']
    index = followingList.index(followingId)
    del followingList[index]
    user.update({
        'followings': followingList
    })
    # update following user its follower list
    followingUser = getUserById(followingId)
    followerList = followingUser['followers']
    index = followerList.index(user.key.name)
    del followerList[index]
    followingUser.update({
        'followers': followerList
    })
    # put in the datastore
    transaction = datastoreClient.transaction()
    with transaction:
        transaction.put(user)
        transaction.put(followingUser)
    return followingUser['username']


@app.route('/unfollow', methods=['POST'])
def unfollow():
    idToken = request.cookies.get("token")
    claims = None
    userData = None
    message = None
    status = None
    if idToken:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                idToken, firebaseRequestAdapter)
            userData = getUserByClaims(claims)
            userNameFollowing = unfollowUser(
                userData, request.form['following-id'])
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
        tweetKeys.append(datastoreClient.key('Tweet', tweetIds[i]))
    return datastoreClient.get_multi(tweetKeys)


def getFeed(user):
    # get all the user entities following by the user
    followingIds = user['followings']
    followingKeys = []
    for i in range(len(followingIds)):
        followingKeys.append(datastoreClient.key('User', followingIds[i]))
    followings = datastoreClient.get_multi(followingKeys)
    # include the himself as he should be able to see his tweets in the feed
    followings.append(user)
    # get last 50 tweets of each users
    tweets = []
    for following in followings:
        tweets += getLast50Tweets(following)
    # sort tweets by antichronoligical order
    tweets.sort(key=lambda x: x['date'], reverse=True)
    # keep just the 50 fist tweets
    tweets = tweets[:50]
    # get the user linked to each tweet thanks to the list of user
    feed = []
    for tweet in tweets:
        feed.append(
            ([x for x in followings if x.key.name == tweet['user']][0], tweet))
    return feed


def deleteTweet(id, user):
    tweetList = user['tweets']
    # get tweet key
    tweetKey = datastoreClient.key('Tweet', id)
    tweet = datastoreClient.get(tweetKey)
    # delete the picture linked to the tweet
    if tweet['file']:
        deleteFileFromStorage(tweet['file'])
    # update user tweet list
    index = tweetList.index(id)
    del tweetList[index]
    user.update({
        'tweets': tweetList
    })
    # update datastore
    transaction = datastoreClient.transaction()
    with transaction:
        transaction.delete(tweetKey)
        transaction.put(user)


@app.route('/delete/<string:id>')
def delete(id):
    idToken = request.cookies.get("token")
    claims = None
    userData = None
    message = None
    status = None
    if idToken:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(
                idToken, firebaseRequestAdapter)
            userData = getUserByClaims(claims)
            deleteTweet(id, userData)
            message = "Your tweet has been deleted"
            status = "success"
        except ValueError as exc:
            message = str(exc)
            status = "error"
    else:
        return render_template('login.html')
    return redirect(getLastUrl(request.referrer, message, status))


def updateTweet(id, content):
    tweet = datastoreClient.get(datastoreClient.key('Tweet', id))
    tweet.update({
        'content': content,
    })
    datastoreClient.put(tweet)


@app.route('/edit_tweet', methods=['POST'])
def editTweet():
    idToken = request.cookies.get("token")
    message = None
    status = None
    if idToken:
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
    storageClient = storage.Client(project=local_constants.PROJECT_NAME)
    bucket = storageClient.bucket(local_constants.PROJECT_STORAGE_BUCKET)
    blob = bucket.blob(filename)
    blob.delete()


def deletePicture(id):
    tweet = datastoreClient.get(datastoreClient.key('Tweet', id))
    deleteFileFromStorage(tweet['file'])
    tweet.update({
        'file': None
    })
    datastoreClient.put(tweet)


@app.route('/delete_pic/<string:id>')
def deletePicForm(id):
    idToken = request.cookies.get("token")
    message = None
    status = None
    if idToken:
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
    tweet = datastoreClient.get(datastoreClient.key('Tweet', id))
    filename = None
    if file.filename != '':
        filename = addFileToStorage(tweet, file)
    # check if file is not a picture
    if not filename:
        return False
    if tweet['file'] != None:
        deleteFileFromStorage(tweet['file'])
    tweet.update({
        'file': filename
    })
    datastoreClient.put(tweet)
    return True


@app.route('/edit_pic', methods=['POST'])
def editPic():
    idToken = request.cookies.get("token")
    message = None
    status = None
    if idToken:
        try:
            if updatePicture(request.form['tweet-id'],
                             request.files['file-name']):
                message = "Your picture has been updated"
                status = "success"
            else:
                message = 'You should choose a picture file (png, jpg, jpeg)'
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
        # case when the url is a search page (with get method)
        if '?search' in referrer:
            join = '&'
        # get rid of former message
        i = referrer.index('message=')
        url = referrer[:(i-1)]
    except:
        url = referrer
    str = ''
    # create the url with get parameters
    if message:
        str = join + 'message=' + message.replace(" ", "+") + '&status='+status
    return url+str


@app.errorhandler(404)
def notFound(error):
    return redirect(url_for('.root', message=error, status="error"))


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)
