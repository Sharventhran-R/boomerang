class RecoveryRequestModel {
  final String id;
  final String reportId;
  final String requesterId;
  final String recipientId;
  final String status;
  final String? message;
  final String? verificationResponse;
  final DateTime createdAt;
  final DateTime updatedAt;
  final String? reportTitle;
  final String? reportType;
  final String? requesterName;
  final String? recipientName;
  final String? requesterEmail;
  final String? recipientEmail;

  const RecoveryRequestModel({
    required this.id,
    required this.reportId,
    required this.requesterId,
    required this.recipientId,
    required this.status,
    this.message,
    this.verificationResponse,
    required this.createdAt,
    required this.updatedAt,
    this.reportTitle,
    this.reportType,
    this.requesterName,
    this.recipientName,
    this.requesterEmail,
    this.recipientEmail,
  });

  factory RecoveryRequestModel.fromJson(Map<String, dynamic> json) {
    final reportJson = json['report'] as Map<String, dynamic>?;
    final requesterJson = json['requester'] as Map<String, dynamic>?;
    final recipientJson = json['recipient'] as Map<String, dynamic>?;

    return RecoveryRequestModel(
      id: json['id'] as String,
      reportId: json['report_id'] as String,
      requesterId: json['requester_id'] as String,
      recipientId: json['recipient_id'] as String,
      status: (json['status'] as String? ?? 'PENDING').toLowerCase(),
      message: json['message'] as String?,
      verificationResponse: json['verification_response'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
      reportTitle: reportJson?['title'] as String?,
      reportType: reportJson?['type'] as String?,
      requesterName: requesterJson?['name'] as String?,
      recipientName: recipientJson?['name'] as String?,
      requesterEmail: requesterJson?['email'] as String?,
      recipientEmail: recipientJson?['email'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'report_id': reportId,
      'requester_id': requesterId,
      'recipient_id': recipientId,
      'status': status.toUpperCase(),
      'message': message,
      'verification_response': verificationResponse,
      'created_at': createdAt.toIso8601String(),
      'updated_at': updatedAt.toIso8601String(),
    };
  }

  RecoveryRequestModel copyWith({
    String? id,
    String? reportId,
    String? requesterId,
    String? recipientId,
    String? status,
    String? message,
    String? verificationResponse,
    DateTime? createdAt,
    DateTime? updatedAt,
    String? reportTitle,
    String? reportType,
    String? requesterName,
    String? recipientName,
    String? requesterEmail,
    String? recipientEmail,
  }) {
    return RecoveryRequestModel(
      id: id ?? this.id,
      reportId: reportId ?? this.reportId,
      requesterId: requesterId ?? this.requesterId,
      recipientId: recipientId ?? this.recipientId,
      status: status ?? this.status,
      message: message ?? this.message,
      verificationResponse: verificationResponse ?? this.verificationResponse,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
      reportTitle: reportTitle ?? this.reportTitle,
      reportType: reportType ?? this.reportType,
      requesterName: requesterName ?? this.requesterName,
      recipientName: recipientName ?? this.recipientName,
      requesterEmail: requesterEmail ?? this.requesterEmail,
      recipientEmail: recipientEmail ?? this.recipientEmail,
    );
  }
}
