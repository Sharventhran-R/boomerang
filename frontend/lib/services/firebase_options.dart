// Firebase Options configuration for Boomerang (Phase 9.6)
import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;
import 'package:flutter/foundation.dart'
    show defaultTargetPlatform, kIsWeb, TargetPlatform;

class DefaultFirebaseOptions {
  static FirebaseOptions get currentPlatform {
    if (kIsWeb) {
      return web;
    }
    switch (defaultTargetPlatform) {
      case TargetPlatform.android:
        return android;
      case TargetPlatform.iOS:
        return ios;
      default:
        throw UnsupportedError(
          'DefaultFirebaseOptions are not supported for this platform.',
        );
    }
  }

  static const FirebaseOptions web = FirebaseOptions(
    apiKey: 'AIzaSyDNuAsqtEEaa8JpChxWhNL1P7lpFNY7JXg',
    appId: '1:70664060069:web:a05b38a426bfdb9f',
    messagingSenderId: '70664060069',
    projectId: 'boomerang-53f86',
    authDomain: 'boomerang-53f86.firebaseapp.com',
    storageBucket: 'boomerang-53f86.firebasestorage.app',
  );

  static const FirebaseOptions android = FirebaseOptions(
    apiKey: 'AIzaSyDNuAsqtEEaa8JpChxWhNL1P7lpFNY7JXg',
    appId: '1:70664060069:android:8fda64b0f7259db6b6a14c',
    messagingSenderId: '70664060069',
    projectId: 'boomerang-53f86',
    storageBucket: 'boomerang-53f86.firebasestorage.app',
  );

  static const FirebaseOptions ios = FirebaseOptions(
    apiKey: 'AIzaSyDNuAsqtEEaa8JpChxWhNL1P7lpFNY7JXg',
    appId: '1:70664060069:ios:placeholder',
    messagingSenderId: '70664060069',
    projectId: 'boomerang-53f86',
    storageBucket: 'boomerang-53f86.firebasestorage.app',
    iosBundleId: 'com.example.frontend',
  );
}
