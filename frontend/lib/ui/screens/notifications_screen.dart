import 'package:flutter/material.dart';
import '../../models/notification_model.dart';
import '../../services/notification_repository.dart';
import '../../theme.dart';
import '../widgets/notification_item_card.dart';
import 'notification_settings_screen.dart';

/// Notification Centre Screen for Boomerang (Phase 9.6).
class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  final ScrollController _scrollController = ScrollController();
  bool _unreadOnly = false;

  @override
  void initState() {
    super.initState();
    _scrollController.addListener(_onScroll);
    NotificationRepository.instance.addListener(_onRepoChanged);

    // Initial load if not already loaded or in mock mode
    if (!NotificationRepository.instance.hasLoaded &&
        !NotificationRepository.instance.isMockMode) {
      NotificationRepository.instance.fetchNotifications(refresh: true);
    }
  }

  void _onRepoChanged() {
    if (mounted) setState(() {});
  }

  void _onScroll() {
    if (_scrollController.position.pixels >=
        _scrollController.position.maxScrollExtent - 200) {
      if (NotificationRepository.instance.hasMore &&
          !NotificationRepository.instance.isLoadingMore) {
        NotificationRepository.instance.fetchNotifications(
          isRead: _unreadOnly ? false : null,
        );
      }
    }
  }

  @override
  void dispose() {
    _scrollController.dispose();
    NotificationRepository.instance.removeListener(_onRepoChanged);
    super.dispose();
  }

  List<NotificationItemModel> _getFilteredNotifications() {
    final list = NotificationRepository.instance.notifications;
    if (_unreadOnly) {
      return list.where((n) => !n.isRead).toList();
    }
    return list;
  }

  @override
  Widget build(BuildContext context) {
    final repo = NotificationRepository.instance;
    final notifications = _getFilteredNotifications();
    final hasUnread = repo.unreadCount > 0;

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        backgroundColor: AppTheme.surface,
        elevation: 0,
        title: const Text(
          'Notifications',
          style: TextStyle(
            fontFamily: 'Hanken Grotesk',
            fontSize: 16,
            fontWeight: FontWeight.bold,
            color: AppTheme.primaryText,
          ),
        ),
        actions: [
          if (hasUnread)
            Tooltip(
              message: 'Mark all as read',
              child: TextButton.icon(
                onPressed: () => repo.markAllAsRead(),
                icon: const Icon(
                  Icons.done_all,
                  size: 16,
                  color: AppTheme.actionPrimary,
                ),
                label: const Text(
                  'Mark all read',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    color: AppTheme.actionPrimary,
                  ),
                ),
              ),
            ),
          IconButton(
            icon: const Icon(
              Icons.tune,
              size: 20,
              color: AppTheme.secondaryText,
            ),
            tooltip: 'Notification Settings',
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => const NotificationSettingsScreen(),
                ),
              );
            },
          ),
          const SizedBox(width: 4),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(48),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            decoration: const BoxDecoration(
              border: Border(
                bottom: BorderSide(color: AppTheme.borderSubtle, width: 0.5),
              ),
            ),
            child: Row(
              children: [
                _buildFilterChip(
                  label: 'All',
                  isSelected: !_unreadOnly,
                  onSelected: () {
                    if (_unreadOnly) {
                      setState(() => _unreadOnly = false);
                    }
                  },
                ),
                const SizedBox(width: 8),
                _buildFilterChip(
                  label: 'Unread (${repo.unreadCount})',
                  isSelected: _unreadOnly,
                  onSelected: () {
                    if (!_unreadOnly) {
                      setState(() => _unreadOnly = true);
                    }
                  },
                ),
                const Spacer(),
                if (repo.total > 0)
                  Text(
                    '${repo.total} ${repo.total == 1 ? 'alert' : 'alerts'}',
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppTheme.mutedText,
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () async {
            await repo.fetchNotifications(
              refresh: true,
              isRead: _unreadOnly ? false : null,
            );
          },
          color: AppTheme.actionPrimary,
          backgroundColor: AppTheme.card,
          child: _buildBody(repo, notifications),
        ),
      ),
    );
  }

  Widget _buildFilterChip({
    required String label,
    required bool isSelected,
    required VoidCallback onSelected,
  }) {
    return InkWell(
      onTap: onSelected,
      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: isSelected ? AppTheme.actionPrimary : AppTheme.card,
          borderRadius: BorderRadius.circular(AppTheme.smallRadius),
          border: Border.all(
            color: isSelected ? Colors.transparent : AppTheme.borderSubtle,
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 12,
            fontWeight: isSelected ? FontWeight.bold : FontWeight.w500,
            color: isSelected
                ? AppTheme.onActionPrimary
                : AppTheme.secondaryText,
          ),
        ),
      ),
    );
  }

  Widget _buildBody(
    NotificationRepository repo,
    List<NotificationItemModel> notifications,
  ) {
    if (repo.isLoading && notifications.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(
              strokeWidth: 2.0,
              color: AppTheme.actionPrimary,
            ),
            SizedBox(height: 16),
            Text(
              'Loading notifications...',
              style: TextStyle(color: AppTheme.secondaryText, fontSize: 13),
            ),
          ],
        ),
      );
    }

    if (repo.errorMessage != null && notifications.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.error_outline,
                size: 40,
                color: AppTheme.secondaryText,
              ),
              const SizedBox(height: 12),
              Text(
                repo.errorMessage!,
                style: const TextStyle(
                  color: AppTheme.secondaryText,
                  fontSize: 13,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: () => repo.fetchNotifications(refresh: true),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppTheme.actionPrimary,
                  foregroundColor: AppTheme.onActionPrimary,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                  ),
                ),
                child: const Text('Try Again'),
              ),
            ],
          ),
        ),
      );
    }

    if (notifications.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32.0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                  color: AppTheme.card,
                  borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: const Icon(
                  Icons.notifications_none_outlined,
                  size: 28,
                  color: AppTheme.secondaryText,
                ),
              ),
              const SizedBox(height: 16),
              Text(
                _unreadOnly
                    ? 'No unread notifications'
                    : 'No notifications yet',
                style: const TextStyle(
                  fontFamily: 'Hanken Grotesk',
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                  color: AppTheme.primaryText,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                _unreadOnly
                    ? 'All your notifications have been marked as read.'
                    : 'Match alerts, recovery requests, and report status updates will appear here.',
                style: const TextStyle(
                  color: AppTheme.secondaryText,
                  fontSize: 12.5,
                  height: 1.4,
                ),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      );
    }

    return ListView.separated(
      controller: _scrollController,
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(16),
      itemCount: notifications.length + (repo.isLoadingMore ? 1 : 0),
      separatorBuilder: (_, _) => const SizedBox(height: 10),
      itemBuilder: (context, index) {
        if (index == notifications.length) {
          return const Padding(
            padding: EdgeInsets.symmetric(vertical: 16.0),
            child: Center(
              child: SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: AppTheme.actionPrimary,
                ),
              ),
            ),
          );
        }

        final item = notifications[index];
        return NotificationItemCard(
          key: ValueKey(item.id),
          item: item,
          onMarkRead: () => repo.markAsRead(item.id),
        );
      },
    );
  }
}
