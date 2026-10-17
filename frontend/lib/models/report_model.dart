import '../ui/widgets/status_label.dart';

class ReportImageModel {
  final String id;
  final String reportId;
  final String objectKey;
  final String contentType;
  final int fileSize;
  final DateTime createdAt;

  const ReportImageModel({
    required this.id,
    required this.reportId,
    required this.objectKey,
    required this.contentType,
    required this.fileSize,
    required this.createdAt,
  });

  factory ReportImageModel.fromJson(Map<String, dynamic> json) {
    return ReportImageModel(
      id: json['id'] as String,
      reportId: (json['report_id'] ?? '') as String,
      objectKey: (json['object_key'] ?? json['image_url'] ?? '') as String,
      contentType: (json['content_type'] ?? 'image/jpeg') as String,
      fileSize: ((json['file_size'] as num?) ?? 0).toInt(),
      createdAt: json['created_at'] != null
          ? DateTime.parse(json['created_at'] as String)
          : DateTime.now(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'report_id': reportId,
      'object_key': objectKey,
      'content_type': contentType,
      'file_size': fileSize,
      'created_at': createdAt.toIso8601String(),
    };
  }
}

class ReportModel {
  final String id;
  final String title;
  final String category;
  final String description;
  final String locationDescription;
  final DateTime dateTime;
  final ReportStatus status;
  final String? reward;
  final String distance;
  final String timeAgo;
  final List<String> photos;
  final bool isUserReport;
  final String? createdByUserId;
  final double? latitude;
  final double? longitude;
  final String? backendStatus;
  final List<ReportImageModel> images;

  const ReportModel({
    required this.id,
    required this.title,
    required this.category,
    required this.description,
    required this.locationDescription,
    required this.dateTime,
    required this.status,
    this.reward,
    this.distance = '0.1 km away',
    this.timeAgo = 'Just now',
    this.photos = const [],
    this.isUserReport = false,
    this.createdByUserId,
    this.latitude,
    this.longitude,
    this.backendStatus,
    this.images = const [],
  });

  bool get isMissing => status == ReportStatus.missing;
  bool get isFound => status == ReportStatus.found;

  ReportModel copyWith({
    String? id,
    String? title,
    String? category,
    String? description,
    String? locationDescription,
    DateTime? dateTime,
    ReportStatus? status,
    String? reward,
    String? distance,
    String? timeAgo,
    List<String>? photos,
    bool? isUserReport,
    String? createdByUserId,
    double? latitude,
    double? longitude,
    String? backendStatus,
    List<ReportImageModel>? images,
  }) {
    return ReportModel(
      id: id ?? this.id,
      title: title ?? this.title,
      category: category ?? this.category,
      description: description ?? this.description,
      locationDescription: locationDescription ?? this.locationDescription,
      dateTime: dateTime ?? this.dateTime,
      status: status ?? this.status,
      reward: reward ?? this.reward,
      distance: distance ?? this.distance,
      timeAgo: timeAgo ?? this.timeAgo,
      photos: photos ?? this.photos,
      isUserReport: isUserReport ?? this.isUserReport,
      createdByUserId: createdByUserId ?? this.createdByUserId,
      latitude: latitude ?? this.latitude,
      longitude: longitude ?? this.longitude,
      backendStatus: backendStatus ?? this.backendStatus,
      images: images ?? this.images,
    );
  }

  factory ReportModel.fromBackendJson(
    Map<String, dynamic> json, {
    String? currentUserId,
  }) {
    final typeStr = (json['type'] as String?)?.toUpperCase() ?? 'MISSING';
    final statusEnum = typeStr == 'MISSING'
        ? ReportStatus.missing
        : ReportStatus.found;

    final rewardVal = json['reward_amount'];
    String? rewardFormatted;
    if (rewardVal != null) {
      final rewardNum = num.tryParse(rewardVal.toString());
      if (rewardNum != null && rewardNum > 0) {
        rewardFormatted =
            '\$${rewardNum.toInt() == rewardNum ? rewardNum.toInt() : rewardNum.toStringAsFixed(2)}';
      }
    }

    final distanceKm = json['distance_km'] as num?;
    final distanceStr = distanceKm != null
        ? '${distanceKm.toDouble().toStringAsFixed(1)} km away'
        : 'Nearby';

    final createdAt = json['created_at'] != null
        ? DateTime.parse(json['created_at'] as String)
        : DateTime.now();

    final eventTime = json['event_time'] != null
        ? DateTime.parse(json['event_time'] as String)
        : createdAt;

    final diff = DateTime.now().difference(createdAt);
    String timeAgoStr;
    if (diff.inMinutes < 1) {
      timeAgoStr = 'Just now';
    } else if (diff.inMinutes < 60) {
      timeAgoStr = '${diff.inMinutes}m ago';
    } else if (diff.inHours < 24) {
      timeAgoStr = '${diff.inHours}h ago';
    } else {
      timeAgoStr = '${diff.inDays}d ago';
    }

    final rawCategory = (json['category'] as String?) ?? 'OTHER';
    final normalizedCategory = _formatCategory(rawCategory);

    final lat = (json['latitude'] as num?)?.toDouble();
    final lon = (json['longitude'] as num?)?.toDouble();
    final locDesc = lat != null && lon != null
        ? 'Sector [${lat.toStringAsFixed(4)}, ${lon.toStringAsFixed(4)}]'
        : 'Coordinates verified';

    final createdBy = json['created_by_user_id'] as String?;
    final isUser = currentUserId != null && createdBy == currentUserId;

    final imageList = <ReportImageModel>[];
    if (json['images'] is List) {
      for (final img in json['images'] as List) {
        if (img is Map<String, dynamic>) {
          imageList.add(ReportImageModel.fromJson(img));
        }
      }
    }

    return ReportModel(
      id: json['id'] as String,
      title: (json['title'] as String?) ?? 'Untitled Report',
      category: normalizedCategory,
      description: (json['description'] as String?) ?? '',
      locationDescription: locDesc,
      dateTime: eventTime,
      status: statusEnum,
      reward: rewardFormatted,
      distance: distanceStr,
      timeAgo: timeAgoStr,
      photos: imageList.map((e) => e.objectKey).toList(),
      isUserReport: isUser,
      createdByUserId: createdBy,
      latitude: lat,
      longitude: lon,
      backendStatus: json['status'] as String?,
      images: imageList,
    );
  }

  static String _formatCategory(String raw) {
    switch (raw.toUpperCase()) {
      case 'ELECTRONICS':
        return 'Electronics';
      case 'DOCUMENT':
      case 'DOCUMENTS':
      case 'DOCUMENTS_KEYS':
        return 'Documents';
      case 'WALLET':
      case 'WALLETS_BAGS':
        return 'Wallet';
      case 'BAG':
        return 'Bag';
      case 'KEYS':
        return 'Keys';
      case 'JEWELRY':
        return 'Jewelry';
      case 'PET':
      case 'PETS':
        return 'Pet';
      case 'VEHICLE':
        return 'Vehicle';
      case 'CLOTHING':
        return 'Clothing';
      case 'OTHER':
      default:
        return 'Other';
    }
  }

  static String toBackendCategory(String category) {
    switch (category.trim().toLowerCase()) {
      case 'electronics':
        return 'ELECTRONICS';
      case 'document':
      case 'documents':
        return 'DOCUMENT';
      case 'wallet':
        return 'WALLET';
      case 'bag':
        return 'BAG';
      case 'keys':
        return 'KEYS';
      case 'jewelry':
        return 'JEWELRY';
      case 'pet':
        return 'PET';
      case 'vehicle':
        return 'VEHICLE';
      case 'clothing':
        return 'CLOTHING';
      default:
        return 'OTHER';
    }
  }
}
