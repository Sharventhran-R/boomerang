import 'report_model.dart';

class MatchModel {
  final String id;
  final String reportMissingId;
  final String reportFoundId;
  final String status;
  final double compositeScore;
  final double scoreIdentity;
  final double scoreCharacteristics;
  final double scoreDistance;
  final double scoreTime;
  final String classification;
  final bool alertEligible;
  final String evidenceSummary;
  final ReportModel oppositeReport;
  final DateTime createdAt;
  final DateTime lastScoredAt;

  const MatchModel({
    required this.id,
    required this.reportMissingId,
    required this.reportFoundId,
    required this.status,
    required this.compositeScore,
    required this.scoreIdentity,
    required this.scoreCharacteristics,
    required this.scoreDistance,
    required this.scoreTime,
    required this.classification,
    required this.alertEligible,
    required this.evidenceSummary,
    required this.oppositeReport,
    required this.createdAt,
    required this.lastScoredAt,
  });

  int get scorePercentage => compositeScore.round().clamp(0, 100);

  String get formattedClassification {
    switch (classification.toUpperCase()) {
      case 'HIGH_PRIORITY':
        return 'High Priority';
      case 'POSSIBLE_MATCH':
        return 'Possible Match';
      case 'LOW_CONFIDENCE':
        return 'Low Confidence';
      case 'DISQUALIFIED':
        return 'Disqualified';
      default:
        return classification;
    }
  }

  factory MatchModel.fromJson(Map<String, dynamic> json) {
    return MatchModel(
      id: json['id'] as String,
      reportMissingId: json['report_missing_id'] as String,
      reportFoundId: json['report_found_id'] as String,
      status: (json['status'] as String?) ?? 'ACTIVE',
      compositeScore: ((json['composite_score'] as num?) ?? 0.0).toDouble(),
      scoreIdentity: ((json['score_identity'] as num?) ?? 0.0).toDouble(),
      scoreCharacteristics: ((json['score_characteristics'] as num?) ?? 0.0)
          .toDouble(),
      scoreDistance: ((json['score_distance'] as num?) ?? 0.0).toDouble(),
      scoreTime: ((json['score_time'] as num?) ?? 0.0).toDouble(),
      classification: (json['classification'] as String?) ?? 'POSSIBLE_MATCH',
      alertEligible: (json['alert_eligible'] as bool?) ?? false,
      evidenceSummary: (json['evidence_summary'] as String?) ?? '',
      oppositeReport: ReportModel.fromBackendJson(
        json['opposite_report'] as Map<String, dynamic>,
      ),
      createdAt: json['created_at'] != null
          ? DateTime.parse(json['created_at'] as String)
          : DateTime.now(),
      lastScoredAt: json['last_scored_at'] != null
          ? DateTime.parse(json['last_scored_at'] as String)
          : DateTime.now(),
    );
  }
}

class MatchDetailModel {
  final String id;
  final String status;
  final double compositeScore;
  final double rawCompositeScore;
  final double contradictionPenalty;
  final double scoreIdentity;
  final double scoreCharacteristics;
  final double scoreDistance;
  final double scoreTime;
  final String classification;
  final bool alertEligible;
  final bool minimumEvidenceSatisfied;
  final String evidenceSummary;
  final Map<String, dynamic> explainabilityDetails;
  final int scoringVersion;
  final DateTime lastScoredAt;
  final DateTime createdAt;
  final DateTime updatedAt;
  final ReportModel reportMissing;
  final ReportModel reportFound;
  final String userRole;

  const MatchDetailModel({
    required this.id,
    required this.status,
    required this.compositeScore,
    required this.rawCompositeScore,
    required this.contradictionPenalty,
    required this.scoreIdentity,
    required this.scoreCharacteristics,
    required this.scoreDistance,
    required this.scoreTime,
    required this.classification,
    required this.alertEligible,
    required this.minimumEvidenceSatisfied,
    required this.evidenceSummary,
    required this.explainabilityDetails,
    required this.scoringVersion,
    required this.lastScoredAt,
    required this.createdAt,
    required this.updatedAt,
    required this.reportMissing,
    required this.reportFound,
    required this.userRole,
  });

  int get scorePercentage => compositeScore.round().clamp(0, 100);

  String get formattedClassification {
    switch (classification.toUpperCase()) {
      case 'HIGH_PRIORITY':
        return 'High Priority';
      case 'POSSIBLE_MATCH':
        return 'Possible Match';
      case 'LOW_CONFIDENCE':
        return 'Low Confidence';
      case 'DISQUALIFIED':
        return 'Disqualified';
      default:
        return classification;
    }
  }

  factory MatchDetailModel.fromJson(Map<String, dynamic> json) {
    return MatchDetailModel(
      id: json['id'] as String,
      status: (json['status'] as String?) ?? 'ACTIVE',
      compositeScore: ((json['composite_score'] as num?) ?? 0.0).toDouble(),
      rawCompositeScore: ((json['raw_composite_score'] as num?) ?? 0.0)
          .toDouble(),
      contradictionPenalty: ((json['contradiction_penalty'] as num?) ?? 0.0)
          .toDouble(),
      scoreIdentity: ((json['score_identity'] as num?) ?? 0.0).toDouble(),
      scoreCharacteristics: ((json['score_characteristics'] as num?) ?? 0.0)
          .toDouble(),
      scoreDistance: ((json['score_distance'] as num?) ?? 0.0).toDouble(),
      scoreTime: ((json['score_time'] as num?) ?? 0.0).toDouble(),
      classification: (json['classification'] as String?) ?? 'POSSIBLE_MATCH',
      alertEligible: (json['alert_eligible'] as bool?) ?? false,
      minimumEvidenceSatisfied:
          (json['minimum_evidence_satisfied'] as bool?) ?? false,
      evidenceSummary: (json['evidence_summary'] as String?) ?? '',
      explainabilityDetails:
          (json['explainability_details'] as Map<String, dynamic>?) ?? {},
      scoringVersion: ((json['scoring_version'] as num?) ?? 1).toInt(),
      lastScoredAt: json['last_scored_at'] != null
          ? DateTime.parse(json['last_scored_at'] as String)
          : DateTime.now(),
      createdAt: json['created_at'] != null
          ? DateTime.parse(json['created_at'] as String)
          : DateTime.now(),
      updatedAt: json['updated_at'] != null
          ? DateTime.parse(json['updated_at'] as String)
          : DateTime.now(),
      reportMissing: ReportModel.fromBackendJson(
        json['report_missing'] as Map<String, dynamic>,
      ),
      reportFound: ReportModel.fromBackendJson(
        json['report_found'] as Map<String, dynamic>,
      ),
      userRole: (json['user_role'] as String?) ?? 'MISSING',
    );
  }
}
