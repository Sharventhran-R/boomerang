import 'package:flutter/material.dart';
import '../../services/recovery_repository.dart';
import '../../theme.dart';
import '../widgets/app_toast.dart';

class RecoveryRequestsScreen extends StatefulWidget {
  const RecoveryRequestsScreen({super.key});

  @override
  State<RecoveryRequestsScreen> createState() => _RecoveryRequestsScreenState();
}

class _RecoveryRequestsScreenState extends State<RecoveryRequestsScreen> {
  String _selectedTab = 'received';
  final Map<String, String> _requestStatuses = {};

  @override
  void initState() {
    super.initState();
    RecoveryRepository.instance.addListener(_onRepoChanged);
    RecoveryRepository.instance.loadRequests();
  }

  @override
  void dispose() {
    RecoveryRepository.instance.removeListener(_onRepoChanged);
    super.dispose();
  }

  void _onRepoChanged() {
    if (mounted) setState(() {});
  }

  void _handleAccept(String id, String senderName, String contact) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.card,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
          side: const BorderSide(color: AppTheme.borderSubtle),
        ),
        title: const Text(
          'Accept Handover Request',
          style: TextStyle(
            color: AppTheme.primaryText,
            fontWeight: FontWeight.bold,
          ),
        ),
        content: Text(
          'Accepting will reveal verified contact details for $senderName to coordinate an in-person public handover.',
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
              setState(() {
                _requestStatuses[id] = 'accepted';
              });
              try {
                await RecoveryRepository.instance.updateRequestStatus(
                  requestId: id,
                  status: 'ACCEPTED',
                );
              } catch (_) {}
              if (!mounted) return;
              AppToast.success(
                context,
                message: 'Handover accepted for $id. Direct contact: $contact',
              );
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTheme.actionPrimary,
              foregroundColor: AppTheme.onActionPrimary,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              ),
            ),
            child: const Text('Reveal Contact & Accept'),
          ),
        ],
      ),
    );
  }

  void _handleDecline(String id, String senderName) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.card,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
          side: const BorderSide(color: AppTheme.borderSubtle),
        ),
        title: const Text(
          'Decline Request',
          style: TextStyle(
            color: AppTheme.primaryText,
            fontWeight: FontWeight.bold,
          ),
        ),
        content: Text(
          'Are you sure you want to decline this request from $senderName? The requester will be notified that the match was declined.',
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
              setState(() {
                _requestStatuses[id] = 'declined';
              });
              try {
                await RecoveryRepository.instance.updateRequestStatus(
                  requestId: id,
                  status: 'REJECTED',
                );
              } catch (_) {}
              if (!mounted) return;
              AppToast.info(context, message: 'Request $id declined.');
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTheme.elevatedSurface,
              foregroundColor: AppTheme.primaryText,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              ),
            ),
            child: const Text('Decline Request'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final receivedList = RecoveryRepository.instance.receivedRequests;
    final sentList = RecoveryRepository.instance.sentRequests;

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        backgroundColor: AppTheme.card,
        elevation: 0,
        title: const Text(
          'Recovery Requests',
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
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Header Block
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Flexible(
                              child: Text(
                                'Recovery Requests',
                                style: Theme.of(context)
                                    .textTheme
                                    .headlineMedium
                                    ?.copyWith(
                                      fontFamily: 'Hanken Grotesk',
                                      fontWeight: FontWeight.bold,
                                      letterSpacing: -0.5,
                                      color: AppTheme.primaryText,
                                    ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            const SizedBox(width: 8),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 7,
                                vertical: 3,
                              ),
                              decoration: BoxDecoration(
                                color: AppTheme.elevatedSurface,
                                borderRadius: BorderRadius.circular(
                                  AppTheme.smallRadius,
                                ),
                                border: Border.all(
                                  color: AppTheme.borderSubtle,
                                ),
                              ),
                              child: Text(
                                '${receivedList.where((r) => r.status == 'pending').length} ACTIVE',
                                style: const TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.bold,
                                  letterSpacing: 0.8,
                                  color: AppTheme.primaryText,
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 2),
                        const Text(
                          'Handover coordination & verified direct contacts',
                          style: TextStyle(
                            color: AppTheme.secondaryText,
                            fontSize: 12,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 10),
                  Container(
                    width: 32,
                    height: 32,
                    decoration: BoxDecoration(
                      color: AppTheme.card,
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                      border: Border.all(color: AppTheme.borderSubtle),
                    ),
                    child: const Icon(
                      Icons.sync_alt,
                      color: AppTheme.secondaryText,
                      size: 16,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),

              // Interactive Tabs
              Container(
                padding: const EdgeInsets.all(4),
                decoration: BoxDecoration(
                  color: AppTheme.card,
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Semantics(
                        button: true,
                        label: 'Received requests tab',
                        selected: _selectedTab == 'received',
                        child: Tooltip(
                          message: 'Show Received Requests',
                          child: InkWell(
                            onTap: () =>
                                setState(() => _selectedTab = 'received'),
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                            child: Container(
                              constraints: const BoxConstraints(minHeight: 40),
                              padding: const EdgeInsets.symmetric(vertical: 8),
                              decoration: BoxDecoration(
                                color: _selectedTab == 'received'
                                    ? AppTheme.actionPrimary
                                    : Colors.transparent,
                                borderRadius: BorderRadius.circular(
                                  AppTheme.smallRadius,
                                ),
                              ),
                              alignment: Alignment.center,
                              child: Text(
                                'Received (${receivedList.length})',
                                style: TextStyle(
                                  color: _selectedTab == 'received'
                                      ? AppTheme.onActionPrimary
                                      : AppTheme.secondaryText,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 13,
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                    Expanded(
                      child: Semantics(
                        button: true,
                        label: 'Sent requests tab',
                        selected: _selectedTab == 'sent',
                        child: Tooltip(
                          message: 'Show Sent Requests',
                          child: InkWell(
                            onTap: () => setState(() => _selectedTab = 'sent'),
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                            child: Container(
                              constraints: const BoxConstraints(minHeight: 40),
                              padding: const EdgeInsets.symmetric(vertical: 8),
                              decoration: BoxDecoration(
                                color: _selectedTab == 'sent'
                                    ? AppTheme.actionPrimary
                                    : Colors.transparent,
                                borderRadius: BorderRadius.circular(
                                  AppTheme.smallRadius,
                                ),
                              ),
                              alignment: Alignment.center,
                              child: Text(
                                'Sent (${sentList.length})',
                                style: TextStyle(
                                  color: _selectedTab == 'sent'
                                      ? AppTheme.onActionPrimary
                                      : AppTheme.secondaryText,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 13,
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 10),

              // Notice Banner
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
                decoration: BoxDecoration(
                  color: AppTheme.card,
                  borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: const Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      Icons.shield_outlined,
                      size: 16,
                      color: AppTheme.secondaryText,
                    ),
                    SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'DIRECT HANDOVER ONLY',
                            style: TextStyle(
                              color: AppTheme.primaryText,
                              fontSize: 10,
                              fontWeight: FontWeight.bold,
                              letterSpacing: 1.0,
                            ),
                          ),
                          SizedBox(height: 2),
                          Text(
                            'Boomerang does not run in-app chat or payments. Accepting reveals direct contacts to arrange safe public handovers.',
                            style: TextStyle(
                              color: AppTheme.secondaryText,
                              fontSize: 11,
                              height: 1.3,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 10),

              // Requests List based on Tab
              if (_selectedTab == 'received') ...[
                if (receivedList.isEmpty)
                  Container(
                    padding: const EdgeInsets.symmetric(vertical: 40),
                    alignment: Alignment.center,
                    child: const Text(
                      'No received recovery requests',
                      style: TextStyle(color: AppTheme.secondaryText),
                    ),
                  )
                else
                  for (int i = 0; i < receivedList.length; i++) ...[
                    if (i > 0) const SizedBox(height: 12),
                    _buildRequestCard(
                      type: receivedList[i].reportType ?? 'MISSING',
                      id: receivedList[i].id,
                      title: receivedList[i].reportTitle ?? 'Item Recovery',
                      subtitle: receivedList[i].reportType == 'MISSING'
                          ? 'Reported lost at Podil / Central'
                          : 'Found item handover coordinate',
                      senderInitials: (receivedList[i].requesterName ?? 'User')
                          .split(' ')
                          .map((s) => s.isNotEmpty ? s[0] : '')
                          .take(2)
                          .join(),
                      senderName: receivedList[i].requesterName ?? 'Maksym D.',
                      senderRole: 'Finder · In-person witness',
                      time:
                          '${receivedList[i].createdAt.hour.toString().padLeft(2, '0')}:${receivedList[i].createdAt.minute.toString().padLeft(2, '0')}',
                      message:
                          receivedList[i].message ??
                          '“I believe I have your item with verified details.”',
                      contact:
                          receivedList[i].requesterEmail ??
                          '+380 67 482 8921 (Direct counter)',
                      currentStatus: receivedList[i].status,
                    ),
                  ],
              ] else ...[
                if (sentList.isEmpty)
                  Container(
                    padding: const EdgeInsets.symmetric(vertical: 40),
                    alignment: Alignment.center,
                    child: const Text(
                      'No sent recovery requests',
                      style: TextStyle(color: AppTheme.secondaryText),
                    ),
                  )
                else
                  for (int i = 0; i < sentList.length; i++) ...[
                    if (i > 0) const SizedBox(height: 12),
                    _buildRequestCard(
                      type: sentList[i].reportType ?? 'MISSING',
                      id: sentList[i].id,
                      title: sentList[i].reportTitle ?? 'Item Recovery',
                      subtitle: 'Lost query sent to Station Lost & Found',
                      senderInitials: (sentList[i].recipientName ?? 'CP')
                          .split(' ')
                          .map((s) => s.isNotEmpty ? s[0] : '')
                          .take(2)
                          .join(),
                      senderName:
                          sentList[i].recipientName ??
                          'Central Station Dispatch',
                      senderRole: 'Municipal Transit Custodian',
                      time:
                          '${sentList[i].createdAt.hour.toString().padLeft(2, '0')}:${sentList[i].createdAt.minute.toString().padLeft(2, '0')}',
                      message:
                          sentList[i].message ??
                          '“Inquiry dispatched to custodian registry.”',
                      contact:
                          sentList[i].recipientEmail ??
                          'desk4@railway.transit.kiev.ua',
                      isOutgoing: true,
                      currentStatus: sentList[i].status,
                    ),
                  ],
              ],
              const SizedBox(height: 40),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildRequestCard({
    required String type,
    required String id,
    required String title,
    required String subtitle,
    required String senderInitials,
    required String senderName,
    required String senderRole,
    required String time,
    required String message,
    required String contact,
    bool isOutgoing = false,
    String? currentStatus,
  }) {
    final status = _requestStatuses[id] ?? currentStatus ?? 'pending';
    final isMissing = type == 'MISSING';

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppTheme.card,
        borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
        border: Border.all(
          color: status == 'accepted'
              ? AppTheme.borderHighlight
              : AppTheme.borderSubtle,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 3,
                    ),
                    decoration: BoxDecoration(
                      color: isMissing
                          ? AppTheme.highlightSurface
                          : AppTheme.surface,
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                      border: Border.all(
                        color: isMissing
                            ? AppTheme.borderHighlight
                            : AppTheme.borderSubtle,
                      ),
                    ),
                    child: Text(
                      type,
                      style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                        color: isMissing
                            ? AppTheme.primaryText
                            : AppTheme.secondaryText,
                        letterSpacing: 1.0,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    id,
                    style: const TextStyle(
                      color: AppTheme.mutedText,
                      fontSize: 10,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 0.5,
                    ),
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: AppTheme.elevatedSurface,
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: Row(
                  children: [
                    Container(
                      width: 6,
                      height: 6,
                      decoration: BoxDecoration(
                        color: status == 'accepted'
                            ? AppTheme.actionPrimary
                            : status == 'declined' || status == 'rejected'
                            ? AppTheme.mutedText
                            : AppTheme.primaryText,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      status == 'accepted'
                          ? (RecoveryRepository.instance.isMockMode
                                ? 'ACCEPTED (MOCK)'
                                : 'ACCEPTED')
                          : status == 'declined' || status == 'rejected'
                          ? (RecoveryRepository.instance.isMockMode
                                ? 'DECLINED (MOCK)'
                                : 'DECLINED')
                          : isOutgoing
                          ? 'SENT'
                          : 'PENDING',
                      style: TextStyle(
                        color: status == 'accepted'
                            ? AppTheme.primaryText
                            : status == 'declined' || status == 'rejected'
                            ? AppTheme.mutedText
                            : AppTheme.secondaryText,
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            title,
            style: const TextStyle(
              fontFamily: 'Hanken Grotesk',
              color: AppTheme.primaryText,
              fontSize: 16,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            subtitle,
            style: const TextStyle(color: AppTheme.secondaryText, fontSize: 12),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppTheme.elevatedSurface,
              borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              border: Border.all(color: AppTheme.borderSubtle),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                  child: Row(
                    children: [
                      Container(
                        width: 32,
                        height: 32,
                        decoration: BoxDecoration(
                          color: AppTheme.surface,
                          borderRadius: BorderRadius.circular(
                            AppTheme.smallRadius,
                          ),
                          border: Border.all(color: AppTheme.borderSubtle),
                        ),
                        alignment: Alignment.center,
                        child: Text(
                          senderInitials,
                          style: const TextStyle(
                            color: AppTheme.primaryText,
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              senderName,
                              style: const TextStyle(
                                color: AppTheme.primaryText,
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            Text(
                              senderRole,
                              style: const TextStyle(
                                color: AppTheme.secondaryText,
                                fontSize: 10,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  time,
                  style: const TextStyle(
                    color: AppTheme.mutedText,
                    fontSize: 10,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppTheme.surface,
              borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              border: Border.all(color: AppTheme.borderSubtle),
            ),
            child: Text(
              message,
              style: const TextStyle(
                color: AppTheme.secondaryText,
                fontSize: 12,
                fontStyle: FontStyle.italic,
                height: 1.4,
              ),
            ),
          ),

          if (status == 'accepted') ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppTheme.elevatedSurface,
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                border: Border.all(color: AppTheme.borderHighlight),
              ),
              child: Row(
                children: [
                  const Icon(
                    Icons.lock_open,
                    size: 16,
                    color: AppTheme.primaryText,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Direct contact coordinates: $contact',
                      style: const TextStyle(
                        color: AppTheme.primaryText,
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],

          const SizedBox(height: 14),

          // Action Buttons
          if (isOutgoing) ...[
            OutlinedButton.icon(
              onPressed: () {
                AppToast.info(
                  context,
                  message:
                      'Outgoing match inquiry is active. Awaiting custodian update.',
                );
              },
              style: OutlinedButton.styleFrom(
                side: const BorderSide(color: AppTheme.borderMuted),
                foregroundColor: AppTheme.primaryText,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                ),
              ),
              icon: const Icon(Icons.track_changes, size: 16),
              label: const Text('View Telemetry Trace'),
            ),
          ] else if (status == 'pending') ...[
            Row(
              children: [
                Expanded(
                  flex: 2,
                  child: ElevatedButton(
                    onPressed: () => _handleAccept(id, senderName, contact),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.actionPrimary,
                      foregroundColor: AppTheme.onActionPrimary,
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(
                          AppTheme.smallRadius,
                        ),
                      ),
                      elevation: 0,
                    ),
                    child: const Text(
                      'Review & Accept',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => _handleDecline(id, senderName),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppTheme.secondaryText,
                      side: const BorderSide(color: AppTheme.borderMuted),
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(
                          AppTheme.smallRadius,
                        ),
                      ),
                    ),
                    child: const Text(
                      'Decline',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                InkWell(
                  onTap: () {
                    AppToast.info(
                      context,
                      message:
                          'Handover Safety: Always meet in well-lit, public locations.',
                    );
                  },
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                  child: Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: AppTheme.elevatedSurface,
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                      border: Border.all(color: AppTheme.borderSubtle),
                    ),
                    child: const Icon(
                      Icons.info_outline,
                      color: AppTheme.secondaryText,
                      size: 18,
                    ),
                  ),
                ),
              ],
            ),
          ] else ...[
            OutlinedButton(
              onPressed: () {
                setState(() => _requestStatuses.remove(id));
              },
              style: OutlinedButton.styleFrom(
                side: const BorderSide(color: AppTheme.borderSubtle),
                foregroundColor: AppTheme.secondaryText,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                ),
              ),
              child: const Text('Reset Decision (Dev Sim)'),
            ),
          ],
        ],
      ),
    );
  }
}
