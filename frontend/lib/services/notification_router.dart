// Centralized Notification Router for Boomerang (Phase 9.7)
import 'dart:async';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import '../models/notification_model.dart';
import '../ui/screens/match_detail_screen.dart';
import '../ui/screens/notifications_screen.dart';
import '../ui/screens/recovery_requests_screen.dart';
import '../ui/screens/report_details_screen.dart';
import '../ui/widgets/app_toast.dart';
import 'auth_service.dart';
import 'notification_repository.dart';

/// Destination screen types handled by the notification router.
enum NotificationDestinationType {
  match,
  report,
  recovery,
  notifications,
  unknown,
}

/// Parsed destination with target parameters.
class NotificationDestination {
  final NotificationDestinationType type;
  final String? resourceId;
  final String? tab;

  const NotificationDestination({
    required this.type,
    this.resourceId,
    this.tab,
  });

  @override
  String toString() =>
      'NotificationDestination(type: $type, id: $resourceId, tab: $tab)';

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is NotificationDestination &&
          runtimeType == other.runtimeType &&
          type == other.type &&
          resourceId == other.resourceId &&
          tab == other.tab;

  @override
  int get hashCode => Object.hash(type, resourceId, tab);
}

/// Normalized intent extracted from a push notification, deep link, or in-app card.
class NotificationRouteIntent {
  final String? notificationId;
  final String type;
  final Map<String, dynamic> data;
  final String? deepLink;
  final DateTime timestamp;

  NotificationRouteIntent({
    this.notificationId,
    required this.type,
    Map<String, dynamic>? data,
    this.deepLink,
    DateTime? timestamp,
  }) : data = data ?? {},
       timestamp = timestamp ?? DateTime.now();

  factory NotificationRouteIntent.fromData(Map<String, dynamic> rawData) {
    final type = (rawData['type'] as String?) ?? 'GENERAL';
    final notificationId =
        (rawData['notification_id'] as String?) ?? (rawData['id'] as String?);
    final deepLink = rawData['deep_link'] as String?;

    return NotificationRouteIntent(
      notificationId: notificationId,
      type: type,
      data: Map<String, dynamic>.from(rawData),
      deepLink: deepLink,
    );
  }

  factory NotificationRouteIntent.fromRemoteMessage(RemoteMessage message) {
    final rawData = Map<String, dynamic>.from(message.data);
    final type = (rawData['type'] as String?) ?? 'GENERAL';
    final notificationId =
        (rawData['notification_id'] as String?) ?? (rawData['id'] as String?);
    final deepLink = rawData['deep_link'] as String?;

    return NotificationRouteIntent(
      notificationId: notificationId,
      type: type,
      data: rawData,
      deepLink: deepLink,
    );
  }

  factory NotificationRouteIntent.fromNotification(NotificationItemModel item) {
    final deepLink = item.data['deep_link'] as String?;
    return NotificationRouteIntent(
      notificationId: item.id,
      type: item.type,
      data: Map<String, dynamic>.from(item.data),
      deepLink: deepLink,
    );
  }

  factory NotificationRouteIntent.fromUri(Uri uri) {
    return NotificationRouteIntent(
      notificationId:
          uri.queryParameters['notification_id'] ?? uri.queryParameters['id'],
      type: uri.queryParameters['type'] ?? 'GENERAL',
      data: uri.queryParameters,
      deepLink: uri.toString(),
    );
  }

  @override
  String toString() =>
      'NotificationRouteIntent(id: $notificationId, type: $type, deepLink: $deepLink)';
}

/// Central router coordinating notification interactions, lifecycle states,
/// authentication gates, and destination screens.
class NotificationRouter {
  static NotificationRouter _instance = NotificationRouter._internal();
  factory NotificationRouter({
    AuthService? authService,
    NotificationRepository? repository,
  }) {
    if (authService != null || repository != null) {
      return NotificationRouter._internal(authService, repository);
    }
    return _instance;
  }
  static NotificationRouter get instance => _instance;

  static void setInstanceForTesting(NotificationRouter router) {
    _instance = router;
  }

  /// Global navigator key registered on MaterialApp for context-free routing.
  static final GlobalKey<NavigatorState> navigatorKey =
      GlobalKey<NavigatorState>();

  final AuthService? _authService;
  final NotificationRepository? _repository;

  AuthService get authService => _authService ?? AuthService.instance;
  NotificationRepository get repository =>
      _repository ?? NotificationRepository.instance;

  NotificationRouteIntent? _pendingIntent;
  String? _lastDispatchedKey;
  DateTime? _lastDispatchedTime;

  bool get hasPendingRoute => _pendingIntent != null;
  NotificationRouteIntent? get pendingIntent => _pendingIntent;
  String? get lastDispatchedKey => _lastDispatchedKey;

  NotificationRouter._internal([this._authService, this._repository]);

  /// Resets internal state for unit testing.
  void resetForTesting() {
    _pendingIntent = null;
    _lastDispatchedKey = null;
    _lastDispatchedTime = null;
  }

  /// Parses a deep link URL, notification type, and data dictionary into a typed destination.
  NotificationDestination parseDestination({
    String? deepLink,
    String? notificationType,
    Map<String, dynamic>? data,
  }) {
    data ??= {};

    // 1. Inspect deepLink if provided (supports custom boomerang:// and HTTPS Web Push URLs)
    if (deepLink != null && deepLink.trim().isNotEmpty) {
      final uri = Uri.tryParse(deepLink.trim());
      if (uri != null) {
        final scheme = uri.scheme.toLowerCase();
        String? segment0;
        String? segment1;
        final queryParams = uri.queryParameters;

        if (scheme == 'boomerang') {
          segment0 = uri.host.toLowerCase();
          segment1 = uri.pathSegments.isNotEmpty ? uri.pathSegments[0] : null;
        } else if (scheme == 'https' || scheme == 'http') {
          if (uri.pathSegments.isNotEmpty) {
            segment0 = uri.pathSegments[0].toLowerCase();
            segment1 = uri.pathSegments.length > 1 ? uri.pathSegments[1] : null;
          }
        }

        if (segment0 == 'matches') {
          final matchId = (segment1 != null && segment1.isNotEmpty)
              ? segment1
              : (data['match_id'] as String?);
          return NotificationDestination(
            type: NotificationDestinationType.match,
            resourceId: matchId,
          );
        } else if (segment0 == 'reports') {
          final reportId = (segment1 != null && segment1.isNotEmpty)
              ? segment1
              : (data['report_id'] as String?);
          return NotificationDestination(
            type: NotificationDestinationType.report,
            resourceId: reportId,
          );
        } else if (segment0 == 'recovery-requests') {
          final tab = queryParams['tab'] ?? (data['tab'] as String?);
          final id =
              queryParams['id'] ??
              (data['recovery_request_id'] as String?) ??
              (data['request_id'] as String?);
          return NotificationDestination(
            type: NotificationDestinationType.recovery,
            resourceId: id,
            tab: tab,
          );
        } else if (segment0 == 'notifications') {
          return const NotificationDestination(
            type: NotificationDestinationType.notifications,
          );
        }
      }
    }

    // 2. Map from notification type enum
    final upperType = (notificationType ?? '').toUpperCase();
    if (upperType == 'MATCH_DETECTED' ||
        upperType == 'MATCH_HIGH_PRIORITY' ||
        upperType == 'MATCH_UPDATED' ||
        upperType.contains('MATCH')) {
      return NotificationDestination(
        type: NotificationDestinationType.match,
        resourceId: data['match_id'] as String?,
      );
    }

    if (upperType == 'RECOVERY_REQUEST_RECEIVED') {
      final reqId =
          (data['recovery_request_id'] as String?) ??
          (data['request_id'] as String?);
      return NotificationDestination(
        type: NotificationDestinationType.recovery,
        resourceId: reqId,
        tab: 'received',
      );
    }

    if (upperType == 'RECOVERY_REQUEST_ACCEPTED' ||
        upperType == 'RECOVERY_REQUEST_REJECTED') {
      final reqId =
          (data['recovery_request_id'] as String?) ??
          (data['request_id'] as String?);
      return NotificationDestination(
        type: NotificationDestinationType.recovery,
        resourceId: reqId,
        tab: 'sent',
      );
    }

    if (upperType == 'RECOVERY_REQUEST_COMPLETED') {
      final reportId = data['report_id'] as String?;
      if (reportId != null && reportId.isNotEmpty) {
        return NotificationDestination(
          type: NotificationDestinationType.report,
          resourceId: reportId,
        );
      }
      final reqId =
          (data['recovery_request_id'] as String?) ??
          (data['request_id'] as String?);
      return NotificationDestination(
        type: NotificationDestinationType.recovery,
        resourceId: reqId,
        tab: 'received',
      );
    }

    if (upperType == 'REPORT_STATUS_CHANGED' ||
        upperType == 'REPORT_EXPIRING' ||
        upperType.contains('REPORT')) {
      final reportId = data['report_id'] as String?;
      return NotificationDestination(
        type: NotificationDestinationType.report,
        resourceId: reportId,
      );
    }

    // 3. Fall back to presence of explicit domain identifiers
    if (data.containsKey('match_id') && data['match_id'] != null) {
      return NotificationDestination(
        type: NotificationDestinationType.match,
        resourceId: data['match_id'] as String?,
      );
    }
    if (data.containsKey('report_id') && data['report_id'] != null) {
      return NotificationDestination(
        type: NotificationDestinationType.report,
        resourceId: data['report_id'] as String?,
      );
    }
    if (data.containsKey('recovery_request_id') ||
        data.containsKey('request_id')) {
      return NotificationDestination(
        type: NotificationDestinationType.recovery,
        resourceId:
            (data['recovery_request_id'] as String?) ??
            (data['request_id'] as String?),
        tab: data['tab'] as String? ?? 'received',
      );
    }

    return const NotificationDestination(
      type: NotificationDestinationType.notifications,
    );
  }

  /// Entry point for FCM RemoteMessage interactions (tap from background or cold start).
  Future<bool> handleMessage(
    RemoteMessage message, {
    BuildContext? context,
  }) async {
    final intent = NotificationRouteIntent.fromRemoteMessage(message);
    return routeIntent(intent, context: context);
  }

  /// Entry point for raw map data.
  Future<bool> handleData(
    Map<String, dynamic> data, {
    BuildContext? context,
  }) async {
    final intent = NotificationRouteIntent.fromData(data);
    return routeIntent(intent, context: context);
  }

  /// Entry point for Notification Centre card taps.
  Future<bool> handleNotification(
    NotificationItemModel item, {
    BuildContext? context,
  }) async {
    final intent = NotificationRouteIntent.fromNotification(item);
    return routeIntent(intent, context: context);
  }

  /// Entry point for deep link URIs.
  Future<bool> handleUri(Uri uri, {BuildContext? context}) async {
    final intent = NotificationRouteIntent.fromUri(uri);
    return routeIntent(intent, context: context);
  }

  /// Main routing method. Enforces authentication, debouncing, and screen resolution.
  Future<bool> routeIntent(
    NotificationRouteIntent intent, {
    BuildContext? context,
  }) async {
    final destination = parseDestination(
      deepLink: intent.deepLink,
      notificationType: intent.type,
      data: intent.data,
    );

    // De-duplicate rapid interactions (e.g., double taps or duplicate OS intents)
    final dispatchKey =
        '${destination.type}_${destination.resourceId}_${destination.tab}_${intent.notificationId}';
    final now = DateTime.now();
    if (_lastDispatchedKey == dispatchKey &&
        _lastDispatchedTime != null &&
        now.difference(_lastDispatchedTime!) <
            const Duration(milliseconds: 1500)) {
      if (kDebugMode) {
        debugPrint(
          'NotificationRouter: Suppressed duplicate navigation ($dispatchKey)',
        );
      }
      return false;
    }

    // Enforce authentication gate:
    // If not authenticated, preserve intent until successful login.
    if (!authService.isAuthenticated) {
      if (kDebugMode) {
        debugPrint(
          'NotificationRouter: User unauthenticated. Pending intent stored: $intent',
        );
      }
      _pendingIntent = intent;
      return false;
    }

    // Mark as read in repository if notificationId is present
    if (intent.notificationId != null && intent.notificationId!.isNotEmpty) {
      try {
        repository.markAsRead(intent.notificationId!).ignore();
        repository.fetchUnreadCount().ignore();
      } catch (_) {}
    }

    // Resolve navigator context
    final nav = context != null
        ? Navigator.of(context)
        : navigatorKey.currentState;

    if (nav == null) {
      // Navigator is not yet mounted (e.g., cold start before first frame)
      _pendingIntent = intent;
      if (kDebugMode) {
        debugPrint(
          'NotificationRouter: Navigator not ready. Stored as pending intent.',
        );
      }
      return false;
    }

    _lastDispatchedKey = dispatchKey;
    _lastDispatchedTime = now;
    _pendingIntent = null;

    final navContext = nav.context;

    // Navigate to resolved destination
    switch (destination.type) {
      case NotificationDestinationType.match:
        final matchId = destination.resourceId;
        if (matchId == null || matchId.trim().isEmpty) {
          if (navContext.mounted) {
            AppToast.error(
              navContext,
              message: 'Match is no longer available or identifier is missing.',
            );
          }
          return false;
        }
        nav.push(
          MaterialPageRoute(
            builder: (_) => MatchDetailScreen(matchId: matchId.trim()),
          ),
        );
        return true;

      case NotificationDestinationType.report:
        final reportId = destination.resourceId;
        if (reportId == null || reportId.trim().isEmpty) {
          if (navContext.mounted) {
            AppToast.error(
              navContext,
              message:
                  'Report is no longer available or identifier is missing.',
            );
          }
          return false;
        }
        nav.push(
          MaterialPageRoute(
            builder: (_) => ReportDetailsScreen(reportId: reportId.trim()),
          ),
        );
        return true;

      case NotificationDestinationType.recovery:
        nav.push(
          MaterialPageRoute(
            builder: (_) => RecoveryRequestsScreen(
              initialTab: destination.tab,
              targetRequestId: destination.resourceId,
            ),
          ),
        );
        return true;

      case NotificationDestinationType.notifications:
        nav.push(
          MaterialPageRoute(builder: (_) => const NotificationsScreen()),
        );
        return true;

      case NotificationDestinationType.unknown:
        if (navContext.mounted) {
          AppToast.info(
            navContext,
            message: 'Notification content is no longer available.',
          );
        }
        return false;
    }
  }

  /// Processes any queued pending route (e.g. after successful login or cold start frame render).
  Future<bool> processPendingRoute() async {
    final intent = _pendingIntent;
    if (intent == null) return false;

    if (!authService.isAuthenticated) {
      return false;
    }

    final nav = navigatorKey.currentState;
    if (nav == null) {
      return false;
    }

    _pendingIntent = null;
    return routeIntent(intent);
  }

  /// Clears any pending navigation intent (called on logout, account switch, or session expiration).
  void clearPendingRoute() {
    _pendingIntent = null;
    _lastDispatchedKey = null;
    _lastDispatchedTime = null;
  }
}
