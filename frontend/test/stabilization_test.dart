import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/main.dart';
import 'package:frontend/ui/screens/choose_report_type_screen.dart';
import 'package:frontend/ui/screens/recovery_requests_screen.dart';
import 'package:frontend/ui/screens/report_details_screen.dart';
import 'package:frontend/ui/screens/settings_screen.dart';

void main() {
  testWidgets('Settings screen layout does not overflow at 390px viewport', (
    WidgetTester tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(const MaterialApp(home: SettingsScreen()));
    await tester.pumpAndSettle();

    expect(find.text('System Preferences'), findsAtLeastNWidgets(1));
    expect(
      find.text('Email Notifications for Recovery Requests'),
      findsOneWidget,
    );
    expect(
      find.text('Location Access: Enabled (High Precision)'),
      findsOneWidget,
    );

    // Verify switch toggle
    final switches = find.byType(Switch);
    expect(switches, findsNWidgets(3));
    await tester.tap(switches.first);
    await tester.pumpAndSettle();
  });

  testWidgets('Home screen search, category filter, and Map View navigation', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const BoomerangApp());
    await tester.pumpAndSettle();

    // Verify initial mock reports
    expect(find.text('MacBook Pro 14'), findsOneWidget);
    expect(find.text('Leather Cardholder & Keys'), findsOneWidget);

    // Filter by category 'Wallet'
    await tester.tap(find.text('Wallet').first);
    await tester.pumpAndSettle();

    expect(find.text('MacBook Pro 14'), findsNothing);
    expect(find.text('Leather Cardholder & Keys'), findsOneWidget);

    // Reset filter with 'All'
    await tester.tap(find.text('All').first);
    await tester.pumpAndSettle();
    expect(find.text('MacBook Pro 14'), findsOneWidget);

    // Test Search input
    final searchInput = find.byType(TextField);
    await tester.enterText(searchInput, 'MacBook');
    await tester.pumpAndSettle();

    expect(find.text('MacBook Pro 14'), findsOneWidget);
    expect(find.text('Leather Cardholder & Keys'), findsNothing);

    // Clear search
    await tester.enterText(searchInput, '');
    await tester.pumpAndSettle();
    expect(find.text('Leather Cardholder & Keys'), findsOneWidget);

    // Test 'Map View' button switches to Map tab
    await tester.tap(find.text('Map View'));
    await tester.pumpAndSettle();

    expect(find.text('Select Location'), findsOneWidget);
  });

  testWidgets('Home action cards open ChooseReportTypeScreen', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const BoomerangApp());
    await tester.pumpAndSettle();

    await tester.tap(find.text('Report Missing'));
    await tester.pumpAndSettle();

    expect(find.byType(ChooseReportTypeScreen), findsOneWidget);
    expect(find.text('Choose Report Type'), findsOneWidget);
    expect(find.text('Report Something Missing'), findsOneWidget);
    expect(find.text('Report Something Found'), findsOneWidget);
  });

  testWidgets('Report card tap opens ReportDetailsScreen', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const BoomerangApp());
    await tester.pumpAndSettle();

    // Tap on the MacBook Pro 14 card
    await tester.tap(find.text('MacBook Pro 14'));
    await tester.pumpAndSettle();

    expect(find.byType(ReportDetailsScreen), findsOneWidget);
    expect(find.text('INCIDENT DETAILS'), findsOneWidget);
    expect(find.text('I Found This Item'), findsOneWidget);
  });

  testWidgets('My Reports pending recovery banner and actions', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const BoomerangApp());
    await tester.pumpAndSettle();

    // Navigate to Reports tab
    await tester.tap(find.text('Reports'));
    await tester.pumpAndSettle();

    expect(find.text('My Reports'), findsOneWidget);
    expect(find.text('1 Pending Recovery Request'), findsOneWidget);

    // Tap pending recovery banner -> opens RecoveryRequestsScreen
    await tester.tap(find.text('1 Pending Recovery Request'));
    await tester.pumpAndSettle();

    expect(find.byType(RecoveryRequestsScreen), findsOneWidget);
  });

  testWidgets('Recovery Requests tabs and decision dialogs', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const MaterialApp(home: RecoveryRequestsScreen()));
    await tester.pumpAndSettle();

    expect(find.text('Received (2)'), findsOneWidget);
    expect(find.text('Sent (1)'), findsOneWidget);
    expect(find.text('MacBook Pro 14" (Space Black)'), findsOneWidget);

    // Switch to Sent tab
    await tester.tap(find.text('Sent (1)'));
    await tester.pumpAndSettle();

    expect(find.text('Rimowa Cabin Bag (Silver)'), findsOneWidget);
    expect(find.text('View Telemetry Trace'), findsOneWidget);

    // Switch back to Received tab
    await tester.tap(find.text('Received (2)'));
    await tester.pumpAndSettle();

    // Tap Review & Accept on first card
    await tester.tap(find.text('Review & Accept').first);
    await tester.pumpAndSettle();

    expect(find.text('Accept Handover Request'), findsOneWidget);
    await tester.tap(find.text('Reveal Contact & Accept'));
    await tester.pumpAndSettle();

    expect(find.text('ACCEPTED (MOCK)'), findsOneWidget);
  });

  testWidgets('Profile navigation to My Reports and logout dialog', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const BoomerangApp());
    await tester.pumpAndSettle();

    // Navigate to Profile
    await tester.tap(find.text('Profile'));
    await tester.pumpAndSettle();

    // Tap 'Browse All Incident Reports'
    final browseBtn = find.text('Browse All Incident Reports');
    await tester.ensureVisible(browseBtn);
    await tester.pumpAndSettle();
    await tester.tap(browseBtn);
    await tester.pumpAndSettle();

    // Should now be on My Reports
    expect(find.text('My Reports'), findsOneWidget);
    expect(find.text('3 ACTIVE'), findsOneWidget);

    // Navigate back to Profile
    await tester.tap(find.text('Profile'));
    await tester.pumpAndSettle();

    // Tap 'Terminate & Log Out'
    final logoutBtn = find.text('Terminate & Log Out');
    await tester.ensureVisible(logoutBtn);
    await tester.pumpAndSettle();
    await tester.tap(logoutBtn);
    await tester.pumpAndSettle();

    expect(find.text('Confirm Session Termination'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(find.text('Confirm Session Termination'), findsNothing);
  });

  testWidgets(
    'Map screen nearby reports sheet expands and collapses on toggle',
    (WidgetTester tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(const BoomerangApp());
      await tester.pumpAndSettle();

      // Navigate to Map tab
      await tester.tap(find.text('Map'));
      await tester.pumpAndSettle();

      // Initially sheet is collapsed showing 'Expand'
      expect(find.text('Nearby Reports'), findsOneWidget);
      expect(find.text('18 items'), findsOneWidget);
      expect(find.text('Expand'), findsOneWidget);
      expect(find.text('Collapse'), findsNothing);

      // Tap Expand button
      await tester.tap(find.text('Expand'));
      await tester.pumpAndSettle();

      // Now sheet should be expanded showing 'Collapse'
      expect(find.text('Collapse'), findsOneWidget);
      expect(find.text('Expand'), findsNothing);

      // Mini list items should be visible
      expect(find.text('MacBook Pro 14 M2'), findsOneWidget);
      expect(find.text('AirPods Pro Case'), findsOneWidget);

      // Tap Collapse button
      await tester.tap(find.text('Collapse'));
      await tester.pumpAndSettle();

      // Sheet collapses back to showing 'Expand'
      expect(find.text('Expand'), findsOneWidget);
      expect(find.text('Collapse'), findsNothing);
    },
  );

  testWidgets(
    'Map screen search bar, neighbouring icons and nearby reports are responsive and do not overlap on desktop',
    (WidgetTester tester) async {
      tester.view.physicalSize = const Size(1280, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(const BoomerangApp());
      await tester.pumpAndSettle();

      // Navigate to Map tab
      await tester.tap(find.text('Map'));
      await tester.pumpAndSettle();

      // Verify search input is visible and not overlapped
      expect(find.byType(TextField), findsOneWidget);
      expect(find.byIcon(Icons.search), findsOneWidget);

      // Verify neighbouring icons are visible and not overlapped
      expect(find.byIcon(Icons.tune), findsOneWidget);
      expect(find.byIcon(Icons.near_me), findsOneWidget);

      // Verify Nearby Reports header
      expect(find.text('Nearby Reports'), findsOneWidget);
      expect(find.text('Expand'), findsOneWidget);

      // Expand Nearby Reports
      await tester.tap(find.text('Expand'));
      await tester.pumpAndSettle();

      // Search bar and neighbouring icons must still be visible and not overlapped
      expect(find.byType(TextField), findsOneWidget);
      expect(find.byIcon(Icons.tune), findsOneWidget);
      expect(find.byIcon(Icons.near_me), findsOneWidget);

      // Expanded report cards visible
      expect(find.text('Collapse'), findsOneWidget);
      expect(find.text('MacBook Pro 14 M2'), findsOneWidget);

      // Collapse
      await tester.tap(find.text('Collapse'));
      await tester.pumpAndSettle();
      expect(find.text('Expand'), findsOneWidget);
    },
  );

  testWidgets(
    'Map screen Alex Morgan avatar button navigates to Profile page',
    (WidgetTester tester) async {
      await tester.pumpWidget(const BoomerangApp());
      await tester.pumpAndSettle();

      // Navigate to Map tab
      await tester.tap(find.text('Map'));
      await tester.pumpAndSettle();

      // Find Alex Morgan avatar button via tooltip
      final avatarFinder = find.byTooltip('Alex Morgan Profile');
      expect(avatarFinder, findsOneWidget);

      // Tap avatar button
      await tester.tap(avatarFinder);
      await tester.pumpAndSettle();

      // Verify we are now on Profile page
      expect(find.text('Alex Morgan'), findsOneWidget);
      expect(find.text('VERIFIED MEMBER'), findsOneWidget);
      expect(find.text('OPERATIONAL SUMMARY'), findsOneWidget);
    },
  );
}
