import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

import 'api.dart';

/// Push notifications through Firebase Cloud Messaging. Everything here is best effort: if Firebase is not available
/// (no Google Play services, no internet) the app simply keeps asking the server for updates, exactly as before.
class Push {
  static bool ready = false;

  static Future<void> init() async {
    try {
      await Firebase.initializeApp();
      await FirebaseMessaging.instance.requestPermission();
      FirebaseMessaging.instance.onTokenRefresh.listen((t) => register(token: t));
      ready = true;
      await register();
    } catch (_) {
      ready = false;
    }
  }

  /// Tell the server which phone belongs to the signed-in person. Called at start-up and again after every sign-in.
  static Future<void> register({String? token}) async {
    if (!ready || Api.session == null) return;
    try {
      final t = token ?? await FirebaseMessaging.instance.getToken();
      if (t != null) await Api.post('/api/push/register', {'token': t});
    } catch (_) {}
  }

  /// Stop sending this phone anything for the person who is signing out.
  static Future<void> forget() async {
    if (!ready || Api.session == null) return;
    try {
      final t = await FirebaseMessaging.instance.getToken();
      if (t != null) await Api.post('/api/push/unregister', {'token': t});
    } catch (_) {}
  }
}
