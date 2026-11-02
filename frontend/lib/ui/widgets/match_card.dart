import 'package:flutter/material.dart';
import '../../models/match_model.dart';
import '../../theme.dart';
import '../screens/match_detail_screen.dart';

class MatchCard extends StatelessWidget {
  final MatchModel match;
  final VoidCallback? onTap;

  const MatchCard({super.key, required this.match, this.onTap});

  @override
  Widget build(BuildContext context) {
    final opp = match.oppositeReport;
    final isHighPriority = match.classification == 'HIGH_PRIORITY';

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: AppTheme.card,
        borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
        border: Border.all(
          color: isHighPriority
              ? AppTheme.actionPrimary.withValues(alpha: 0.6)
              : AppTheme.borderSubtle,
          width: isHighPriority ? 1.5 : 1.0,
        ),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
          onTap:
              onTap ??
              () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => MatchDetailScreen(matchId: match.id),
                  ),
                );
              },
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Header: Score Badge + Classification + Distance
                Row(
                  children: [
                    // Score Badge
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: isHighPriority
                            ? AppTheme.actionPrimary
                            : AppTheme.elevatedSurface,
                        borderRadius: BorderRadius.circular(
                          AppTheme.smallRadius,
                        ),
                        border: Border.all(
                          color: isHighPriority
                              ? AppTheme.actionPrimary
                              : AppTheme.borderMuted,
                        ),
                      ),
                      child: Text(
                        '${match.scorePercentage}% MATCH',
                        style: TextStyle(
                          fontFamily: 'Hanken Grotesk',
                          color: isHighPriority
                              ? AppTheme.onActionPrimary
                              : AppTheme.primaryText,
                          fontSize: 11,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 0.5,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    // Classification Label
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: AppTheme.elevatedSurface,
                        borderRadius: BorderRadius.circular(
                          AppTheme.smallRadius,
                        ),
                        border: Border.all(color: AppTheme.borderSubtle),
                      ),
                      child: Text(
                        match.formattedClassification.toUpperCase(),
                        style: const TextStyle(
                          color: AppTheme.secondaryText,
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 0.3,
                        ),
                      ),
                    ),
                    const Spacer(),
                    // Distance
                    Row(
                      children: [
                        const Icon(
                          Icons.location_on_outlined,
                          size: 14,
                          color: AppTheme.secondaryText,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          opp.distance,
                          style: const TextStyle(
                            color: AppTheme.secondaryText,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                // Title and Opposite Report Type
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Category Icon box
                    Container(
                      width: 40,
                      height: 40,
                      decoration: BoxDecoration(
                        color: AppTheme.elevatedSurface,
                        borderRadius: BorderRadius.circular(
                          AppTheme.smallRadius,
                        ),
                        border: Border.all(color: AppTheme.borderSubtle),
                      ),
                      child: Icon(
                        _getCategoryIcon(opp.category),
                        size: 20,
                        color: AppTheme.primaryText,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            opp.title,
                            style: const TextStyle(
                              fontFamily: 'Hanken Grotesk',
                              color: AppTheme.primaryText,
                              fontSize: 15,
                              fontWeight: FontWeight.w600,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                          const SizedBox(height: 2),
                          Text(
                            '${opp.isFound ? 'Found Report' : 'Missing Report'} · ${opp.category}',
                            style: const TextStyle(
                              color: AppTheme.secondaryText,
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const Icon(
                      Icons.chevron_right,
                      color: AppTheme.secondaryText,
                      size: 20,
                    ),
                  ],
                ),
                if (match.evidenceSummary.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      color: AppTheme.elevatedSurface,
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                      border: Border.all(
                        color: AppTheme.borderSubtle.withValues(alpha: 0.5),
                      ),
                    ),
                    child: Text(
                      match.evidenceSummary,
                      style: const TextStyle(
                        color: AppTheme.secondaryText,
                        fontSize: 11,
                        height: 1.3,
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  IconData _getCategoryIcon(String category) {
    final cat = category.toLowerCase();
    if (cat.contains('wallet')) return Icons.account_balance_wallet_outlined;
    if (cat.contains('pet')) return Icons.pets_outlined;
    if (cat.contains('key')) return Icons.key_outlined;
    if (cat.contains('bag')) return Icons.shopping_bag_outlined;
    if (cat.contains('jewelry')) return Icons.watch_outlined;
    if (cat.contains('document')) return Icons.description_outlined;
    if (cat.contains('vehicle')) return Icons.directions_car_outlined;
    if (cat.contains('clothing')) return Icons.checkroom_outlined;
    return Icons.devices_outlined;
  }
}
