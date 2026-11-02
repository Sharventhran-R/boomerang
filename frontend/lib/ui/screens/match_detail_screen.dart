import 'package:flutter/material.dart';
import '../../models/match_model.dart';
import '../../models/report_model.dart';
import '../../services/match_repository.dart';
import '../../services/recovery_repository.dart';
import '../../theme.dart';
import '../widgets/app_toast.dart';
import '../widgets/status_label.dart';
import 'report_details_screen.dart';

class MatchDetailScreen extends StatefulWidget {
  final String matchId;
  final MatchDetailModel? initialMatch;

  const MatchDetailScreen({
    super.key,
    required this.matchId,
    this.initialMatch,
  });

  @override
  State<MatchDetailScreen> createState() => _MatchDetailScreenState();
}

class _MatchDetailScreenState extends State<MatchDetailScreen> {
  MatchDetailModel? _match;
  bool _isLoading = true;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    if (widget.initialMatch != null) {
      _match = widget.initialMatch;
      _isLoading = false;
    } else {
      _loadDetail();
    }
  }

  Future<void> _loadDetail() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final detail = await MatchRepository.instance.fetchMatchDetail(
        widget.matchId,
      );
      if (mounted) {
        setState(() {
          _match = detail;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _errorMessage = e.toString();
          _isLoading = false;
        });
      }
    }
  }

  void _openReportDetails(ReportModel report) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => ReportDetailsScreen(
          reportId: report.id,
          title: report.title,
          category: report.category,
          distance: report.distance,
          timeAgo: report.timeAgo,
          status: report.status,
          reward: report.reward,
          description: report.description,
          locationDescription: report.locationDescription,
        ),
      ),
    );
  }

  void _showInitiateRecoveryDialog(MatchDetailModel match) {
    final targetReport = match.userRole == 'MISSING'
        ? match.reportFound
        : match.reportMissing;

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.card,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
          side: const BorderSide(color: AppTheme.borderSubtle),
        ),
        title: const Text(
          'Initiate Recovery Contact',
          style: TextStyle(
            color: AppTheme.primaryText,
            fontWeight: FontWeight.bold,
          ),
        ),
        content: Text(
          'A recovery verification request will be sent to coordinate a safe in-person public handover for "${targetReport.title}".',
          style: const TextStyle(color: AppTheme.secondaryText, height: 1.4),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text(
              'Cancel',
              style: TextStyle(color: AppTheme.secondaryText),
            ),
          ),
          ElevatedButton(
            onPressed: () async {
              Navigator.pop(ctx);
              try {
                await RecoveryRepository.instance.createRecoveryRequest(
                  reportId: targetReport.id,
                  message:
                      'Recovery request initiated from match score of ${match.scorePercentage}%.',
                );
                if (!mounted) return;
                AppToast.success(
                  context,
                  message: 'Recovery request sent for ${targetReport.title}.',
                );
              } catch (e) {
                if (!mounted) return;
                AppToast.error(
                  context,
                  message: 'Failed to send recovery request: $e',
                );
              }
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTheme.actionPrimary,
              foregroundColor: AppTheme.onActionPrimary,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              ),
            ),
            child: const Text('Send Recovery Request'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        backgroundColor: AppTheme.card,
        elevation: 0,
        title: const Text(
          'Match Telemetry',
          style: TextStyle(
            fontFamily: 'Hanken Grotesk',
            color: AppTheme.primaryText,
            fontWeight: FontWeight.w600,
            fontSize: 16,
          ),
        ),
      ),
      body: SafeArea(
        child: _isLoading
            ? const Center(
                child: CircularProgressIndicator(color: AppTheme.primaryText),
              )
            : _errorMessage != null && _match == null
            ? Center(
                child: Padding(
                  padding: const EdgeInsets.all(24.0),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(
                        Icons.error_outline,
                        size: 40,
                        color: AppTheme.secondaryText,
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'Match Unavailable',
                        style: TextStyle(
                          fontFamily: 'Hanken Grotesk',
                          color: AppTheme.primaryText,
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        _errorMessage!,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: AppTheme.secondaryText,
                          fontSize: 12,
                        ),
                      ),
                      const SizedBox(height: 16),
                      ElevatedButton(
                        onPressed: _loadDetail,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.actionPrimary,
                          foregroundColor: AppTheme.onActionPrimary,
                        ),
                        child: const Text('Retry'),
                      ),
                    ],
                  ),
                ),
              )
            : _buildContent(_match!),
      ),
    );
  }

  Widget _buildContent(MatchDetailModel match) {
    final isHighPriority = match.classification == 'HIGH_PRIORITY';
    final userIsMissing = match.userRole == 'MISSING';
    final myReport = userIsMissing ? match.reportMissing : match.reportFound;
    final matchedReport = userIsMissing
        ? match.reportFound
        : match.reportMissing;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // 1. Hero Composite Score Card
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: AppTheme.card,
              borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
              border: Border.all(
                color: isHighPriority
                    ? AppTheme.actionPrimary.withValues(alpha: 0.8)
                    : AppTheme.borderSubtle,
                width: isHighPriority ? 1.5 : 1.0,
              ),
            ),
            child: Column(
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${match.scorePercentage}%',
                          style: const TextStyle(
                            fontFamily: 'Hanken Grotesk',
                            fontSize: 48,
                            fontWeight: FontWeight.w700,
                            color: AppTheme.primaryText,
                            letterSpacing: -1,
                          ),
                        ),
                        const SizedBox(height: 2),
                        const Text(
                          'COMPOSITE MATCH SCORE',
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: AppTheme.secondaryText,
                            letterSpacing: 0.8,
                          ),
                        ),
                      ],
                    ),
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 5,
                          ),
                          decoration: BoxDecoration(
                            color: isHighPriority
                                ? AppTheme.actionPrimary
                                : AppTheme.elevatedSurface,
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                          ),
                          child: Text(
                            match.formattedClassification.toUpperCase(),
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.bold,
                              color: isHighPriority
                                  ? AppTheme.onActionPrimary
                                  : AppTheme.primaryText,
                              letterSpacing: 0.5,
                            ),
                          ),
                        ),
                        if (match.alertEligible) ...[
                          const SizedBox(height: 6),
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 3,
                            ),
                            decoration: BoxDecoration(
                              color: AppTheme.elevatedSurface,
                              borderRadius: BorderRadius.circular(
                                AppTheme.smallRadius,
                              ),
                              border: Border.all(color: AppTheme.borderSubtle),
                            ),
                            child: const Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(
                                  Icons.notifications_active_outlined,
                                  size: 12,
                                  color: AppTheme.secondaryText,
                                ),
                                SizedBox(width: 4),
                                Text(
                                  'ALERT ELIGIBLE',
                                  style: TextStyle(
                                    fontSize: 9,
                                    fontWeight: FontWeight.w600,
                                    color: AppTheme.secondaryText,
                                    letterSpacing: 0.5,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ],
                    ),
                  ],
                ),
                if (match.evidenceSummary.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppTheme.elevatedSurface,
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                      border: Border.all(color: AppTheme.borderSubtle),
                    ),
                    child: Text(
                      match.evidenceSummary,
                      style: const TextStyle(
                        color: AppTheme.primaryText,
                        fontSize: 13,
                        height: 1.4,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 20),

          // 2. Report Comparison Section
          const Text(
            'CORRESPONDING REPORTS',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: AppTheme.secondaryText,
              letterSpacing: 0.8,
            ),
          ),
          const SizedBox(height: 8),

          // Your Report Card
          _buildReportSummaryCard(
            title: 'Your Report (${myReport.isMissing ? 'Missing' : 'Found'})',
            report: myReport,
            isMyReport: true,
          ),
          const SizedBox(height: 10),

          // Matched Report Card
          _buildReportSummaryCard(
            title:
                'Matched Candidate (${matchedReport.isMissing ? 'Missing' : 'Found'})',
            report: matchedReport,
            isMyReport: false,
            onViewReport: () => _openReportDetails(matchedReport),
          ),
          const SizedBox(height: 24),

          // 3. Multi-Signal Explainability Telemetry
          const Text(
            'SCORING BREAKDOWN & EVIDENCE SIGNALS',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: AppTheme.secondaryText,
              letterSpacing: 0.8,
            ),
          ),
          const SizedBox(height: 12),

          // Signal I: Identity
          _buildSignalCard(
            signalCode: 'SIGNAL I',
            signalName: 'Item Identity',
            score: match.scoreIdentity,
            icon: Icons.fingerprint,
            details: _buildIdentityDetails(match.explainabilityDetails),
          ),
          const SizedBox(height: 12),

          // Signal C: Physical Characteristics
          _buildSignalCard(
            signalCode: 'SIGNAL C',
            signalName: 'Physical Characteristics',
            score: match.scoreCharacteristics,
            icon: Icons.palette_outlined,
            details: _buildCharacteristicsDetails(match.explainabilityDetails),
          ),
          const SizedBox(height: 12),

          // Signal D: Geographic Proximity
          _buildSignalCard(
            signalCode: 'SIGNAL D',
            signalName: 'Geographic Distance',
            score: match.scoreDistance,
            icon: Icons.near_me_outlined,
            details: _buildDistanceDetails(match.explainabilityDetails),
          ),
          const SizedBox(height: 12),

          // Signal T: Temporal Compatibility
          _buildSignalCard(
            signalCode: 'SIGNAL T',
            signalName: 'Temporal Compatibility',
            score: match.scoreTime,
            icon: Icons.schedule_outlined,
            details: _buildTimeDetails(match.explainabilityDetails),
          ),
          const SizedBox(height: 28),

          // 4. Action Buttons
          if (userIsMissing) ...[
            ElevatedButton.icon(
              onPressed: () => _showInitiateRecoveryDialog(match),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTheme.actionPrimary,
                foregroundColor: AppTheme.onActionPrimary,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                ),
                elevation: 0,
              ),
              icon: const Icon(Icons.handshake_outlined, size: 20),
              label: const Text(
                'Initiate Recovery Contact',
                style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold),
              ),
            ),
            const SizedBox(height: 12),
          ],

          OutlinedButton.icon(
            onPressed: () => _openReportDetails(matchedReport),
            style: OutlinedButton.styleFrom(
              foregroundColor: AppTheme.primaryText,
              side: const BorderSide(color: AppTheme.borderMuted),
              padding: const EdgeInsets.symmetric(vertical: 14),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              ),
            ),
            icon: const Icon(Icons.open_in_new, size: 18),
            label: const Text(
              'View Matched Report Full Details',
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
            ),
          ),
          const SizedBox(height: 20),
        ],
      ),
    );
  }

  Widget _buildReportSummaryCard({
    required String title,
    required ReportModel report,
    required bool isMyReport,
    VoidCallback? onViewReport,
  }) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.card,
        borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
        border: Border.all(
          color: isMyReport ? AppTheme.borderSubtle : AppTheme.borderMuted,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                title.toUpperCase(),
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  color: isMyReport
                      ? AppTheme.secondaryText
                      : AppTheme.primaryText,
                  letterSpacing: 0.5,
                ),
              ),
              if (onViewReport != null)
                InkWell(
                  onTap: onViewReport,
                  child: const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          'View',
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: AppTheme.primaryText,
                          ),
                        ),
                        SizedBox(width: 2),
                        Icon(
                          Icons.arrow_forward_ios,
                          size: 10,
                          color: AppTheme.primaryText,
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            report.title,
            style: const TextStyle(
              fontFamily: 'Hanken Grotesk',
              fontSize: 15,
              fontWeight: FontWeight.w600,
              color: AppTheme.primaryText,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            report.description,
            style: const TextStyle(
              fontSize: 12,
              color: AppTheme.secondaryText,
              height: 1.3,
            ),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Icon(
                report.status == ReportStatus.missing
                    ? Icons.search
                    : Icons.check_circle_outline,
                size: 14,
                color: AppTheme.secondaryText,
              ),
              const SizedBox(width: 4),
              Text(
                report.category,
                style: const TextStyle(
                  fontSize: 11,
                  color: AppTheme.secondaryText,
                ),
              ),
              const SizedBox(width: 12),
              const Icon(
                Icons.location_on_outlined,
                size: 14,
                color: AppTheme.secondaryText,
              ),
              const SizedBox(width: 4),
              Expanded(
                child: Text(
                  report.locationDescription,
                  style: const TextStyle(
                    fontSize: 11,
                    color: AppTheme.secondaryText,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSignalCard({
    required String signalCode,
    required String signalName,
    required double score,
    required IconData icon,
    required Widget details,
  }) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.card,
        borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
        border: Border.all(color: AppTheme.borderSubtle),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18, color: AppTheme.primaryText),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      signalCode,
                      style: const TextStyle(
                        fontSize: 9,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.secondaryText,
                        letterSpacing: 0.5,
                      ),
                    ),
                    Text(
                      signalName,
                      style: const TextStyle(
                        fontFamily: 'Hanken Grotesk',
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.primaryText,
                      ),
                    ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: AppTheme.elevatedSurface,
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                  border: Border.all(color: AppTheme.borderMuted),
                ),
                child: Text(
                  '${score.toStringAsFixed(1)} / 100',
                  style: const TextStyle(
                    fontFamily: 'Hanken Grotesk',
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    color: AppTheme.primaryText,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          const Divider(color: AppTheme.borderSubtle, height: 1),
          const SizedBox(height: 10),
          details,
        ],
      ),
    );
  }

  Widget _buildIdentityDetails(Map<String, dynamic> explainability) {
    final identity =
        (explainability['identity'] as Map<String, dynamic>?) ?? {};
    final matchedBrand = identity['matched_brand'] as String?;
    final matchedModel = identity['matched_model'] as String?;
    final categoryScore = identity['category_score'];
    final brandModelScore = identity['brand_model_score'];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildTelemetryRow(
          'Category Alignment',
          categoryScore != null ? '$categoryScore pts' : 'Aligned',
        ),
        if (matchedBrand != null)
          _buildTelemetryRow('Matched Brand', matchedBrand),
        if (matchedModel != null)
          _buildTelemetryRow('Matched Model', matchedModel),
        if (brandModelScore != null)
          _buildTelemetryRow('Brand & Model Points', '$brandModelScore pts'),
      ],
    );
  }

  Widget _buildCharacteristicsDetails(Map<String, dynamic> explainability) {
    final chars =
        (explainability['characteristics'] as Map<String, dynamic>?) ?? {};
    final matchedColors = (chars['matched_colors'] as List?)?.join(', ') ?? '';
    final matchedCases = (chars['matched_cases'] as List?)?.join(', ') ?? '';
    final matchedMarks =
        (chars['matched_distinctive_marks'] as List?)?.join(', ') ?? '';
    final conflictingColors =
        (chars['conflicting_colors'] as List?)?.join(', ') ?? '';
    final hasContradiction = (chars['has_contradiction'] as bool?) ?? false;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (matchedColors.isNotEmpty)
          _buildTelemetryRow('Matched Colors', matchedColors),
        if (matchedCases.isNotEmpty)
          _buildTelemetryRow('Matched Enclosure/Case', matchedCases),
        if (matchedMarks.isNotEmpty)
          _buildTelemetryRow('Distinctive Marks', matchedMarks),
        if (hasContradiction)
          _buildTelemetryRow(
            'Contradiction Detected',
            conflictingColors.isNotEmpty
                ? conflictingColors
                : 'Conflicting attributes',
            isWarning: true,
          ),
        if (matchedColors.isEmpty &&
            matchedCases.isEmpty &&
            matchedMarks.isEmpty &&
            !hasContradiction)
          const Text(
            'Compatible physical traits without conflicting descriptors.',
            style: TextStyle(fontSize: 12, color: AppTheme.secondaryText),
          ),
      ],
    );
  }

  Widget _buildDistanceDetails(Map<String, dynamic> explainability) {
    final distance =
        (explainability['distance'] as Map<String, dynamic>?) ?? {};
    final distanceMeters = distance['distance_meters'];
    final distanceKm = distance['distance_km'];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (distanceKm != null)
          _buildTelemetryRow('Spatial Proximity', '$distanceKm km'),
        if (distanceMeters != null)
          _buildTelemetryRow(
            'PostGIS Computed Radius',
            '${(distanceMeters as num).round()} meters (<= 5,000m barrier)',
          ),
      ],
    );
  }

  Widget _buildTimeDetails(Map<String, dynamic> explainability) {
    final time = (explainability['time'] as Map<String, dynamic>?) ?? {};
    final deltaHours = time['delta_hours'];
    final deltaDays = time['delta_days'];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (deltaHours != null)
          _buildTelemetryRow(
            'Incident Time Delta',
            '${(deltaHours as num).toStringAsFixed(1)} hours (${(deltaDays as num?)?.toStringAsFixed(1) ?? "0"} days)',
          ),
        const Text(
          'Time compatibility evaluated using incident timestamp delta.',
          style: TextStyle(fontSize: 11, color: AppTheme.secondaryText),
        ),
      ],
    );
  }

  Widget _buildTelemetryRow(
    String label,
    String value, {
    bool isWarning = false,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: const TextStyle(fontSize: 12, color: AppTheme.secondaryText),
          ),
          Text(
            value,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: isWarning ? AppTheme.primaryText : AppTheme.primaryText,
            ),
          ),
        ],
      ),
    );
  }
}
