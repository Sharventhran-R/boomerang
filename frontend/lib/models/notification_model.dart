// Notification Models for Boomerang (Phase 9.6)

enum DevicePlatform {
  android,
  ios,
  web;

  String toApiString() {
    switch (this) {
      case DevicePlatform.android:
        return 'ANDROID';
      case DevicePlatform.ios:
        return 'IOS';
      case DevicePlatform.web:
        return 'WEB';
    }
  }

  static DevicePlatform fromApiString(String value) {
    switch (value.toUpperCase()) {
      case 'ANDROID':
        return DevicePlatform.android;
      case 'IOS':
        return DevicePlatform.ios;
      case 'WEB':
        return DevicePlatform.web;
      default:
        return DevicePlatform.android;
    }
  }
}

class NotificationItemModel {
  final String id;
  final String type;
  final String title;
  final String body;
  final Map<String, dynamic> data;
  final String priority;
  final bool isRead;
  final DateTime? readAt;
  final DateTime createdAt;

  const NotificationItemModel({
    required this.id,
    required this.type,
    required this.title,
    required this.body,
    required this.data,
    required this.priority,
    required this.isRead,
    this.readAt,
    required this.createdAt,
  });

  bool get isHighPriority => priority == 'HIGH' || priority == 'URGENT';

  NotificationItemModel copyWith({bool? isRead, DateTime? readAt}) {
    return NotificationItemModel(
      id: id,
      type: type,
      title: title,
      body: body,
      data: data,
      priority: priority,
      isRead: isRead ?? this.isRead,
      readAt: readAt ?? this.readAt,
      createdAt: createdAt,
    );
  }

  factory NotificationItemModel.fromJson(Map<String, dynamic> json) {
    return NotificationItemModel(
      id: json['id'] as String,
      type: json['type'] as String? ?? 'GENERAL',
      title: json['title'] as String? ?? '',
      body: json['body'] as String? ?? '',
      data: json['data'] is Map<String, dynamic>
          ? Map<String, dynamic>.from(json['data'] as Map)
          : <String, dynamic>{},
      priority: json['priority'] as String? ?? 'DEFAULT',
      isRead: json['is_read'] as bool? ?? false,
      readAt: json['read_at'] != null
          ? DateTime.tryParse(json['read_at'] as String)
          : null,
      createdAt: json['created_at'] != null
          ? DateTime.parse(json['created_at'] as String)
          : DateTime.now(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'type': type,
      'title': title,
      'body': body,
      'data': data,
      'priority': priority,
      'is_read': isRead,
      'read_at': readAt?.toIso8601String(),
      'created_at': createdAt.toIso8601String(),
    };
  }
}

class NotificationListResponse {
  final List<NotificationItemModel> items;
  final int unreadCount;
  final int page;
  final int pageSize;
  final int total;
  final int totalPages;

  const NotificationListResponse({
    required this.items,
    required this.unreadCount,
    required this.page,
    required this.pageSize,
    required this.total,
    required this.totalPages,
  });

  bool get hasMore => page < totalPages;

  factory NotificationListResponse.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'] as List<dynamic>? ?? [];
    final items = rawItems
        .map((e) => NotificationItemModel.fromJson(e as Map<String, dynamic>))
        .toList();

    return NotificationListResponse(
      items: items,
      unreadCount: json['unread_count'] as int? ?? 0,
      page: json['page'] as int? ?? 1,
      pageSize: json['page_size'] as int? ?? 20,
      total: json['total'] as int? ?? 0,
      totalPages: json['total_pages'] as int? ?? 1,
    );
  }
}

class UnreadCountModel {
  final int unreadCount;

  const UnreadCountModel({required this.unreadCount});

  factory UnreadCountModel.fromJson(Map<String, dynamic> json) {
    return UnreadCountModel(unreadCount: json['unread_count'] as int? ?? 0);
  }
}

class RegisterDeviceRequest {
  final String deviceId;
  final String fcmToken;
  final DevicePlatform platform;
  final String? deviceModel;
  final String? appVersion;

  const RegisterDeviceRequest({
    required this.deviceId,
    required this.fcmToken,
    required this.platform,
    this.deviceModel,
    this.appVersion,
  });

  Map<String, dynamic> toJson() {
    return {
      'device_id': deviceId,
      'fcm_token': fcmToken,
      'platform': platform.toApiString(),
      if (deviceModel != null) 'device_model': deviceModel,
      if (appVersion != null) 'app_version': appVersion,
    };
  }
}

class DeviceResponseModel {
  final String id;
  final String deviceId;
  final DevicePlatform platform;
  final String? deviceModel;
  final String? appVersion;
  final bool isActive;
  final DateTime lastActiveAt;
  final DateTime createdAt;

  const DeviceResponseModel({
    required this.id,
    required this.deviceId,
    required this.platform,
    this.deviceModel,
    this.appVersion,
    required this.isActive,
    required this.lastActiveAt,
    required this.createdAt,
  });

  factory DeviceResponseModel.fromJson(Map<String, dynamic> json) {
    return DeviceResponseModel(
      id: json['id'] as String,
      deviceId: json['device_id'] as String,
      platform: DevicePlatform.fromApiString(
        json['platform'] as String? ?? 'ANDROID',
      ),
      deviceModel: json['device_model'] as String?,
      appVersion: json['app_version'] as String?,
      isActive: json['is_active'] as bool? ?? true,
      lastActiveAt: json['last_active_at'] != null
          ? DateTime.parse(json['last_active_at'] as String)
          : DateTime.now(),
      createdAt: json['created_at'] != null
          ? DateTime.parse(json['created_at'] as String)
          : DateTime.now(),
    );
  }
}

class NotificationPreferenceModel {
  final bool pushEnabled;
  final bool inAppEnabled;
  final bool matchAlertsEnabled;
  final double matchMinScore;
  final bool matchHighPriorityOnly;
  final bool recoveryUpdatesEnabled;
  final bool reportStatusEnabled;
  final bool quietHoursEnabled;
  final String? quietHoursStart;
  final String? quietHoursEnd;
  final DateTime? updatedAt;

  const NotificationPreferenceModel({
    required this.pushEnabled,
    required this.inAppEnabled,
    required this.matchAlertsEnabled,
    required this.matchMinScore,
    required this.matchHighPriorityOnly,
    required this.recoveryUpdatesEnabled,
    required this.reportStatusEnabled,
    required this.quietHoursEnabled,
    this.quietHoursStart,
    this.quietHoursEnd,
    this.updatedAt,
  });

  factory NotificationPreferenceModel.defaultPreferences() {
    return const NotificationPreferenceModel(
      pushEnabled: true,
      inAppEnabled: true,
      matchAlertsEnabled: true,
      matchMinScore: 75.0,
      matchHighPriorityOnly: false,
      recoveryUpdatesEnabled: true,
      reportStatusEnabled: true,
      quietHoursEnabled: false,
    );
  }

  factory NotificationPreferenceModel.fromJson(Map<String, dynamic> json) {
    return NotificationPreferenceModel(
      pushEnabled: json['push_enabled'] as bool? ?? true,
      inAppEnabled: json['in_app_enabled'] as bool? ?? true,
      matchAlertsEnabled: json['match_alerts_enabled'] as bool? ?? true,
      matchMinScore: (json['match_min_score'] as num?)?.toDouble() ?? 75.0,
      matchHighPriorityOnly: json['match_high_priority_only'] as bool? ?? false,
      recoveryUpdatesEnabled: json['recovery_updates_enabled'] as bool? ?? true,
      reportStatusEnabled: json['report_status_enabled'] as bool? ?? true,
      quietHoursEnabled: json['quiet_hours_enabled'] as bool? ?? false,
      quietHoursStart: json['quiet_hours_start'] as String?,
      quietHoursEnd: json['quiet_hours_end'] as String?,
      updatedAt: json['updated_at'] != null
          ? DateTime.tryParse(json['updated_at'] as String)
          : null,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'push_enabled': pushEnabled,
      'in_app_enabled': inAppEnabled,
      'match_alerts_enabled': matchAlertsEnabled,
      'match_min_score': matchMinScore,
      'match_high_priority_only': matchHighPriorityOnly,
      'recovery_updates_enabled': recoveryUpdatesEnabled,
      'report_status_enabled': reportStatusEnabled,
      'quiet_hours_enabled': quietHoursEnabled,
      'quiet_hours_start': quietHoursStart,
      'quiet_hours_end': quietHoursEnd,
      'updated_at': updatedAt?.toIso8601String(),
    };
  }
}

class UpdateNotificationPreferenceRequest {
  final bool? pushEnabled;
  final bool? inAppEnabled;
  final bool? matchAlertsEnabled;
  final double? matchMinScore;
  final bool? matchHighPriorityOnly;
  final bool? recoveryUpdatesEnabled;
  final bool? reportStatusEnabled;
  final bool? quietHoursEnabled;
  final String? quietHoursStart;
  final String? quietHoursEnd;

  const UpdateNotificationPreferenceRequest({
    this.pushEnabled,
    this.inAppEnabled,
    this.matchAlertsEnabled,
    this.matchMinScore,
    this.matchHighPriorityOnly,
    this.recoveryUpdatesEnabled,
    this.reportStatusEnabled,
    this.quietHoursEnabled,
    this.quietHoursStart,
    this.quietHoursEnd,
  });

  Map<String, dynamic> toJson() {
    final map = <String, dynamic>{};
    if (pushEnabled != null) map['push_enabled'] = pushEnabled;
    if (inAppEnabled != null) map['in_app_enabled'] = inAppEnabled;
    if (matchAlertsEnabled != null) {
      map['match_alerts_enabled'] = matchAlertsEnabled;
    }
    if (matchMinScore != null) map['match_min_score'] = matchMinScore;
    if (matchHighPriorityOnly != null) {
      map['match_high_priority_only'] = matchHighPriorityOnly;
    }
    if (recoveryUpdatesEnabled != null) {
      map['recovery_updates_enabled'] = recoveryUpdatesEnabled;
    }
    if (reportStatusEnabled != null) {
      map['report_status_enabled'] = reportStatusEnabled;
    }
    if (quietHoursEnabled != null) {
      map['quiet_hours_enabled'] = quietHoursEnabled;
    }
    if (quietHoursStart != null) map['quiet_hours_start'] = quietHoursStart;
    if (quietHoursEnd != null) map['quiet_hours_end'] = quietHoursEnd;
    return map;
  }
}
