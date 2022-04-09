'use strict';
window.addEventListener('load', function () {

    var modalMessage = document.getElementById('custom-message')
    if (modalMessage) {
        var message = new bootstrap.Modal(modalMessage, {
            keyboard: true
        })
        message.show()
    }

    var modalCreation = document.getElementById('modal-creation')

    if (modalCreation) {
        var modal = new bootstrap.Modal(modalCreation, {
            backdrop: 'static',
            keyboard: false,
            focus: true
        })
        modal.show()
    }

    var signOut = document.getElementById('sign-out')
    if (signOut) {
        signOut.onclick = function () {
            firebase.auth().signOut();
            document.cookie = "token=" + ";path=/";
            window.location.replace("/login");
        }
    }

    var uiConfig = {
        signInSuccessUrl: '/',
        signInOptions: [
            firebase.auth.EmailAuthProvider.PROVIDER_ID
        ]
    };
    var authContainer = document.getElementById('firebase-auth-container')

    firebase.auth().onAuthStateChanged(function (user) {
        if (user) {
            user.getIdToken().then(function (token) {
                document.cookie = "token=" + token + ";path=/";
            });
        } else {
            if (authContainer) {
                var ui = new firebaseui.auth.AuthUI(firebase.auth());
                ui.start('#firebase-auth-container', uiConfig);
            }
            document.cookie = "token=" + ";path=/";
        }
    }, function (error) {
        console.log(error);
        alert('Unable to log in: ' + error);
    });

    var search = document.getElementById('search-object')
    search.addEventListener('click', function () {
        var isUser = search.value == 'user'
        search.innerHTML = isUser ? '<i class="fa-solid fa-at fa-2x"></i>' : '<i class="fa-solid fa-message fa-2x"></i>'
        document.getElementById('search-input').setAttribute('placeholder', isUser ? 'Username' : 'Content of the tweet')
        document.getElementById('search-form').setAttribute('action', isUser ? '/search_user' : '/search_tweet')
        search.value = isUser ? 'tweet' : 'user'
    });
    $(function () {
        $('.pop').on('click', function () {
            $('.imagepreview').attr('src', $(this).find('img').attr('src'));
            $('#imagemodal').modal('show');
        });
    });

    var text_max = 280;
    $('#count-tweet').html('0 / ' + text_max);

    $('#tweet-text').keyup(function () {
        var text_length = $('#tweet-text').val().length;
        $('#count-tweet').html(text_length + ' / ' + text_max);
    });
    var bio_max = 140;
    $('#count-tweet').html('0 / ' + bio_max);

    $('#bio-text').keyup(function () {
        var text_length = $('#bio-text').val().length;
        $('#count-tweet').html(text_length + ' / ' + bio_max);
    });
});

