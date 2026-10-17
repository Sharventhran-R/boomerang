import 'package:flutter/material.dart';
import '../../models/report_model.dart';
import '../../services/recovery_repository.dart';
import '../../services/report_repository.dart';
import '../../theme.dart';
import '../widgets/app_toast.dart';
import '../widgets/status_label.dart';

class ReportDetailsScreen extends StatefulWidget {
  final String? reportId;
  final String title;
  final String category;
  final String distance;
  final String timeAgo;
  final ReportStatus status;
  final String? reward;
  final String locationDescription;
  final String description;

  const ReportDetailsScreen({
    super.key,
    this.reportId,
    this.title = 'MacBook Pro 14" (Space Black)',
    this.category = 'Electronics',
    this.distance = '0.4 km away',
    this.timeAgo = '25m ago',
    this.status = ReportStatus.missing,
    this.reward = '\$250',
    this.locationDescription = 'Espresso Bar, Podil',
    this.description =
        'M2 Pro, 16GB RAM, space black finish. Left in black neoprene sleeve on the corner table near window. Serial number on file with system registry.',
  });

  @override
  State<ReportDetailsScreen> createState() => _ReportDetailsScreenState();
}

class _ReportDetailsScreenState extends State<ReportDetailsScreen> {
  bool _isSaved = false;
  ReportModel? _loadedReport;
  bool _isLoading = false;
  String? _errorMessage;

  String get _displayTitle => _loadedReport?.title ?? widget.title;
  String get _displayCategory => _loadedReport?.category ?? widget.category;
  String get _displayDistance => _loadedReport?.distance ?? widget.distance;
  String get _displayTimeAgo => _loadedReport?.timeAgo ?? widget.timeAgo;
  ReportStatus get _displayStatus => _loadedReport?.status ?? widget.status;
  String? get _displayReward => _loadedReport?.reward ?? widget.reward;
  String get _displayLocationDescription =>
      _loadedReport?.locationDescription ?? widget.locationDescription;
  String get _displayDescription =>
      _loadedReport?.description ?? widget.description;

  @override
  void initState() {
    super.initState();
    if (widget.reportId != null) {
      _loadReport();
    }
  }

  Future<void> _loadReport() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });
    try {
      final report = await ReportRepository.instance.fetchReportById(
        widget.reportId!,
      );
      if (mounted) {
        setState(() {
          _loadedReport = report;
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        backgroundColor: AppTheme.card,
        elevation: 0,
        title: const Text(
          'Report Details',
          style: TextStyle(
            color: AppTheme.primaryText,
            fontWeight: FontWeight.w600,
            fontSize: 16,
          ),
        ),
        leading: Tooltip(
          message: 'Back',
          child: IconButton(
            icon: const Icon(Icons.arrow_back, color: AppTheme.primaryText),
            tooltip: 'Back',
            onPressed: () => Navigator.of(context).pop(),
          ),
        ),
        actions: [
          Tooltip(
            message: 'Share Report',
            child: IconButton(
              icon: const Icon(
                Icons.share,
                color: AppTheme.primaryText,
                size: 20,
              ),
              tooltip: 'Share Report',
              onPressed: () {
                AppToast.info(
                  context,
                  message: 'Report link copied to clipboard.',
                );
              },
            ),
          ),
          Tooltip(
            message: _isSaved ? 'Remove Bookmark' : 'Bookmark Report',
            child: IconButton(
              icon: Icon(
                _isSaved ? Icons.bookmark : Icons.bookmark_border,
                color: _isSaved
                    ? AppTheme.actionPrimary
                    : AppTheme.secondaryText,
                size: 20,
              ),
              tooltip: _isSaved ? 'Remove Bookmark' : 'Bookmark Report',
              onPressed: () {
                setState(() => _isSaved = !_isSaved);
                AppToast.info(
                  context,
                  message: _isSaved
                      ? 'Report bookmarked.'
                      : 'Bookmark removed.',
                );
              },
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: _isLoading
            ? const Center(
                child: CircularProgressIndicator(color: AppTheme.primaryText),
              )
            : _errorMessage != null && _loadedReport == null
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
                        'Report Unavailable',
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
                        onPressed: _loadReport,
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
            : SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Hero Item Showcase Frame
                    Container(
                      height: 200,
                      decoration: BoxDecoration(
                        color: AppTheme.card,
                        borderRadius: BorderRadius.circular(
                          AppTheme.defaultRadius,
                        ),
                        border: Border.all(color: AppTheme.borderSubtle),
                      ),
                      child: Stack(
                        alignment: Alignment.center,
                        children: [
                          // Grid background lines
                          Positioned.fill(
                            child: CustomPaint(painter: _GridPatternPainter()),
                          ),
                          Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Container(
                                width: 72,
                                height: 72,
                                decoration: BoxDecoration(
                                  color: AppTheme.elevatedSurface,
                                  borderRadius: BorderRadius.circular(
                                    AppTheme.defaultRadius,
                                  ),
                                  border: Border.all(
                                    color: AppTheme.borderMuted,
                                  ),
                                ),
                                child: Icon(
                                  _displayCategory.toLowerCase().contains(
                                        'wallet',
                                      )
                                      ? Icons.account_balance_wallet
                                      : _displayCategory.toLowerCase().contains(
                                          'pet',
                                        )
                                      ? Icons.pets
                                      : Icons.laptop_mac,
                                  size: 36,
                                  color: AppTheme.primaryText,
                                ),
                              ),
                              const SizedBox(height: 12),
                              Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 10,
                                  vertical: 4,
                                ),
                                decoration: BoxDecoration(
                                  color: AppTheme.surface,
                                  borderRadius: BorderRadius.circular(
                                    AppTheme.smallRadius,
                                  ),
                                  border: Border.all(
                                    color: AppTheme.borderSubtle,
                                  ),
                                ),
                                child: const Text(
                                  'PHOTO PREVIEW',
                                  style: TextStyle(
                                    fontSize: 10,
                                    fontWeight: FontWeight.bold,
                                    letterSpacing: 0.8,
                                    color: AppTheme.secondaryText,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Status and Badges Row
                    Row(
                      children: [
                        StatusLabel(status: _displayStatus),
                        if (_displayReward != null) ...[
                          const SizedBox(width: 8),
                          RewardLabel(amount: _displayReward!),
                        ],
                        const Spacer(),
                        Text(
                          _displayTimeAgo,
                          style: const TextStyle(
                            color: AppTheme.secondaryText,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),

                    Text(
                      _displayTitle,
                      style: const TextStyle(
                        fontFamily: 'Hanken Grotesk',
                        color: AppTheme.primaryText,
                        fontSize: 22,
                        fontWeight: FontWeight.bold,
                        letterSpacing: -0.3,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '$_displayCategory · $_displayDistance',
                      style: const TextStyle(
                        color: AppTheme.secondaryText,
                        fontSize: 13,
                      ),
                    ),
                    const SizedBox(height: 20),

                    // Telemetry & Details Card
                    Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: AppTheme.card,
                        borderRadius: BorderRadius.circular(
                          AppTheme.defaultRadius,
                        ),
                        border: Border.all(color: AppTheme.borderSubtle),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'INCIDENT DETAILS',
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.bold,
                              letterSpacing: 1.0,
                              color: AppTheme.secondaryText,
                            ),
                          ),
                          const SizedBox(height: 12),
                          Text(
                            _displayDescription,
                            style: const TextStyle(
                              color: AppTheme.primaryText,
                              fontSize: 14,
                              height: 1.5,
                            ),
                          ),
                          const SizedBox(height: 16),
                          const Divider(color: AppTheme.borderSubtle),
                          const SizedBox(height: 12),
                          Row(
                            children: [
                              const Icon(
                                Icons.location_on_outlined,
                                size: 18,
                                color: AppTheme.secondaryText,
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  _displayLocationDescription,
                                  style: const TextStyle(
                                    color: AppTheme.primaryText,
                                    fontSize: 13,
                                    fontWeight: FontWeight.w500,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 24),

                    // Action Buttons
                    Semantics(
                      button: true,
                      label: _displayStatus == ReportStatus.missing
                          ? 'I Found This Item. Initiate handover contact'
                          : 'Claim This Item. Verify ownership',
                      child: ElevatedButton.icon(
                        onPressed: () {
                          showDialog(
                            context: context,
                            builder: (ctx) => AlertDialog(
                              backgroundColor: AppTheme.card,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(
                                  AppTheme.defaultRadius,
                                ),
                                side: const BorderSide(
                                  color: AppTheme.borderSubtle,
                                ),
                              ),
                              title: Text(
                                _displayStatus == ReportStatus.missing
                                    ? 'Initiate Handover Contact'
                                    : 'Claim Item Ownership',
                                style: const TextStyle(
                                  color: AppTheme.primaryText,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              content: Text(
                                'A recovery notification will be sent to coordinate a safe in-person public handover for $_displayTitle.',
                                style: const TextStyle(
                                  color: AppTheme.secondaryText,
                                  height: 1.4,
                                ),
                              ),
                              actions: [
                                TextButton(
                                  onPressed: () => Navigator.pop(ctx),
                                  child: const Text(
                                    'Cancel',
                                    style: TextStyle(
                                      color: AppTheme.secondaryText,
                                    ),
                                  ),
                                ),
                                ElevatedButton(
                                  onPressed: () async {
                                    Navigator.pop(ctx);
                                    try {
                                      final targetId =
                                          widget.reportId ??
                                          _loadedReport?.id ??
                                          'rep-unknown';
                                      await RecoveryRepository.instance
                                          .createRecoveryRequest(
                                            reportId: targetId,
                                            message:
                                                'Direct recovery request initiated for $_displayTitle.',
                                          );
                                      if (context.mounted) {
                                        AppToast.success(
                                          context,
                                          message:
                                              'Recovery request sent for $_displayTitle.',
                                        );
                                      }
                                    } catch (e) {
                                      if (context.mounted) {
                                        AppToast.error(
                                          context,
                                          message:
                                              'Failed to send recovery request: $e',
                                        );
                                      }
                                    }
                                  },
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: AppTheme.actionPrimary,
                                    foregroundColor: AppTheme.onActionPrimary,
                                    shape: RoundedRectangleBorder(
                                      borderRadius: BorderRadius.circular(
                                        AppTheme.smallRadius,
                                      ),
                                    ),
                                  ),
                                  child: const Text('Send Recovery Request'),
                                ),
                              ],
                            ),
                          );
                        },
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.actionPrimary,
                          foregroundColor: AppTheme.onActionPrimary,
                          padding: const EdgeInsets.symmetric(vertical: 14),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                          ),
                          elevation: 0,
                        ),
                        icon: const Icon(Icons.handshake, size: 20),
                        label: Text(
                          widget.status == ReportStatus.missing
                              ? 'I Found This Item'
                              : 'Claim This Item',
                          style: const TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Semantics(
                      button: true,
                      label:
                          'Report Discrepancy. Flag duplicate or inaccurate report',
                      child: OutlinedButton.icon(
                        onPressed: () {
                          showDialog(
                            context: context,
                            builder: (ctx) => AlertDialog(
                              backgroundColor: AppTheme.card,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(
                                  AppTheme.defaultRadius,
                                ),
                                side: const BorderSide(
                                  color: AppTheme.borderSubtle,
                                ),
                              ),
                              title: const Text(
                                'Flag Discrepancy',
                                style: TextStyle(
                                  color: AppTheme.primaryText,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              content: const Text(
                                'Submit an audit review request if this telemetry post contains invalid coordinates, duplicate serials, or fraudulent claims.',
                                style: TextStyle(
                                  color: AppTheme.secondaryText,
                                  height: 1.4,
                                ),
                              ),
                              actions: [
                                TextButton(
                                  onPressed: () => Navigator.pop(ctx),
                                  child: const Text(
                                    'Dismiss',
                                    style: TextStyle(
                                      color: AppTheme.secondaryText,
                                    ),
                                  ),
                                ),
                                ElevatedButton(
                                  onPressed: () {
                                    Navigator.pop(ctx);
                                    AppToast.info(
                                      context,
                                      message: 'Discrepancy logged for review.',
                                    );
                                  },
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: AppTheme.elevatedSurface,
                                    foregroundColor: AppTheme.primaryText,
                                    shape: RoundedRectangleBorder(
                                      borderRadius: BorderRadius.circular(
                                        AppTheme.smallRadius,
                                      ),
                                    ),
                                  ),
                                  child: const Text('Submit Flag'),
                                ),
                              ],
                            ),
                          );
                        },
                        style: OutlinedButton.styleFrom(
                          foregroundColor: AppTheme.primaryText,
                          side: const BorderSide(color: AppTheme.borderMuted),
                          padding: const EdgeInsets.symmetric(vertical: 14),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                          ),
                        ),
                        icon: const Icon(Icons.flag_outlined, size: 18),
                        label: const Text(
                          'Report Discrepancy',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
      ),
    );
  }
}

class _GridPatternPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppTheme.borderSubtle.withValues(alpha: 0.3)
      ..strokeWidth = 1.0;

    const step = 20.0;
    for (double x = 0; x <= size.width; x += step) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
    for (double y = 0; y <= size.height; y += step) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
