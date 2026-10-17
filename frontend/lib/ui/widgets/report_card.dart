import 'package:flutter/material.dart';
import '../../theme.dart';
import 'status_label.dart';

class ReportCard extends StatelessWidget {
  final String title;
  final String category;
  final String distance;
  final String timeAgo;
  final ReportStatus status;
  final String? reward;
  final Widget? bottomActions;
  final VoidCallback? onTap;

  const ReportCard({
    super.key,
    required this.title,
    required this.category,
    required this.distance,
    required this.timeAgo,
    required this.status,
    this.reward,
    this.bottomActions,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final statusStr = status == ReportStatus.missing ? 'Missing' : 'Found';
    final rewardStr = reward != null ? ', Reward $reward' : '';
    final accessibilityLabel =
        '$statusStr report: $title. Category: $category. Distance: $distance. Reported: $timeAgo$rewardStr.';

    return Semantics(
      button: true,
      label: accessibilityLabel,
      child: Tooltip(
        message: 'View details for $title',
        child: Container(
          margin: const EdgeInsets.only(bottom: 12),
          decoration: BoxDecoration(
            color: AppTheme.card,
            borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
            border: Border.all(color: AppTheme.borderSubtle, width: 1.0),
          ),
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Architectural Thumbnail Frame
                      Semantics(
                        label: 'Item image placeholder',
                        child: Container(
                          width: 88,
                          height: 88,
                          decoration: BoxDecoration(
                            color: AppTheme.surface,
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                            border: Border.all(color: AppTheme.borderMuted),
                          ),
                          child: const Center(
                            child: Icon(
                              Icons.inventory_2_outlined,
                              color: AppTheme.mutedText,
                              size: 28,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 14),
                      // Editorial Report Metadata Stack
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Wrap(
                              spacing: 6,
                              runSpacing: 4,
                              children: [
                                StatusLabel(status: status),
                                if (reward != null)
                                  RewardLabel(amount: reward!),
                              ],
                            ),
                            const SizedBox(height: 6),
                            Text(
                              title,
                              style: const TextStyle(
                                fontSize: 15,
                                fontWeight: FontWeight.w600,
                                color: AppTheme.primaryText,
                                letterSpacing: -0.015,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            const SizedBox(height: 2),
                            Text(
                              category.toUpperCase(),
                              style: const TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.w600,
                                color: AppTheme.mutedText,
                                letterSpacing: 0.6,
                              ),
                            ),
                            const SizedBox(height: 10),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Flexible(
                                  child: Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      const Icon(
                                        Icons.near_me_outlined,
                                        size: 13,
                                        color: AppTheme.secondaryText,
                                      ),
                                      const SizedBox(width: 4),
                                      Flexible(
                                        child: Text(
                                          distance,
                                          style: const TextStyle(
                                            fontSize: 11.5,
                                            color: AppTheme.secondaryText,
                                            fontWeight: FontWeight.w500,
                                          ),
                                          overflow: TextOverflow.ellipsis,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                const SizedBox(width: 8),
                                Text(
                                  timeAgo,
                                  style: const TextStyle(
                                    fontSize: 11,
                                    color: AppTheme.mutedText,
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  if (bottomActions != null) ...[
                    const SizedBox(height: 12),
                    const Divider(color: AppTheme.divider, height: 1),
                    const SizedBox(height: 10),
                    bottomActions!,
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
