// Boomerang Web Push Service Worker (Phase 9.6)
importScripts('https://www.gstatic.com/firebasejs/10.7.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.7.1/firebase-messaging-compat.js');

// Firebase client configuration for boomerang-53f86
firebase.initializeApp({
  apiKey: "AIzaSyDNuAsqtEEaa8JpChxWhNL1P7lpFNY7JXg",
  projectId: "boomerang-53f86",
  messagingSenderId: "70664060069",
  appId: "1:70664060069:web:a05b38a426bfdb9f",
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
  const title = (payload.notification && payload.notification.title) ||
                (payload.data && payload.data.title) ||
                'Boomerang Notification';
  const options = {
    body: (payload.notification && payload.notification.body) ||
          (payload.data && payload.data.body) || '',
    icon: '/favicon.png',
    data: payload.data || {},
  };

  self.registration.showNotification(title, options);
});

