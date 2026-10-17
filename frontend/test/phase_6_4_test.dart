import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/main.dart';
import 'package:frontend/services/report_repository.dart';
import 'package:frontend/ui/screens/choose_report_type_screen.dart';
import 'package:frontend/ui/screens/create_report_screen.dart';
import 'package:frontend/ui/screens/home_screen.dart';
import 'package:frontend/ui/screens/map_screen.dart';
import 'package:frontend/ui/screens/my_reports_screen.dart';
import 'package:frontend/ui/screens/report_details_screen.dart';
import 'package:frontend/ui/widgets/status_label.dart';

void main() {
  setUp(() {
    ReportRepository.instance.resetToDefault();
  });

  group('Phase 6.4: Report Creation Form & Validation Unit/Widget Tests', () {
    testWidgets(
      'Opening CreateReportScreen for MISSING initializes status and shows reward field',
      (WidgetTester tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));
        await tester.pumpWidget(
          const MaterialApp(
            home: CreateReportScreen(initialStatus: ReportStatus.missing),
          ),
        );
        await tester.pumpAndSettle();

        expect(find.text('Create Report'), findsOneWidget);
        expect(find.text('Report Missing'), findsOneWidget);
        expect(find.text('Report Found'), findsOneWidget);
        expect(find.text('Item Title *'), findsOneWidget);
        expect(find.text('Offer a Reward'), findsOneWidget);
        expect(find.text('Publish Missing Report'), findsOneWidget);
      },
    );

    testWidgets('Opening CreateReportScreen for FOUND hides reward field', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      await tester.pumpWidget(
        const MaterialApp(
          home: CreateReportScreen(initialStatus: ReportStatus.found),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Create Report'), findsOneWidget);
      // Reward section must NOT be present for FOUND
      expect(find.text('Offer a Reward'), findsNothing);
      expect(find.text('Publish Found Report'), findsOneWidget);
    });

    testWidgets(
      'Toggling from MISSING to FOUND hides reward and clears previously entered reward',
      (WidgetTester tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));
        await tester.pumpWidget(
          const MaterialApp(
            home: CreateReportScreen(initialStatus: ReportStatus.missing),
          ),
        );
        await tester.pumpAndSettle();

        // Enter a reward in the reward field
        final rewardField = find.widgetWithText(
          TextFormField,
          'Enter custom reward amount (optional)',
        );
        expect(rewardField, findsOneWidget);
        await tester.enterText(rewardField, '75');
        await tester.pumpAndSettle();

        // Switch to Report Found
        await tester.ensureVisible(find.text('Report Found'));
        await tester.tap(find.text('Report Found'));
        await tester.pumpAndSettle();

        // Reward field is now hidden
        expect(find.text('Offer a Reward'), findsNothing);

        // Switch back to Report Missing - the field is cleared
        await tester.ensureVisible(find.text('Report Missing'));
        await tester.tap(find.text('Report Missing'));
        await tester.pumpAndSettle();
        expect(find.text('Offer a Reward'), findsOneWidget);
        final restoredRewardField = find.widgetWithText(
          TextFormField,
          'Enter custom reward amount (optional)',
        );
        await tester.ensureVisible(restoredRewardField);
        final textFormFieldWidget = tester.widget<TextFormField>(
          restoredRewardField,
        );
        expect(textFormFieldWidget.controller?.text, isEmpty);
      },
    );

    testWidgets('Required-field validation displays inline error messages', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      await tester.pumpWidget(
        const MaterialApp(
          home: CreateReportScreen(initialStatus: ReportStatus.missing),
        ),
      );
      await tester.pumpAndSettle();

      // Tap Publish button without filling required fields
      final submitButton = find.text('Publish Missing Report');
      await tester.ensureVisible(submitButton);
      await tester.tap(submitButton);
      await tester.pumpAndSettle();

      // Inline validation errors appear
      expect(find.text('Please enter an item title.'), findsOneWidget);
      expect(find.text('Please enter a description.'), findsOneWidget);
      expect(find.text('Please enter a location.'), findsOneWidget);
    });

    testWidgets('Negative reward validation rejects negative values', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      await tester.pumpWidget(
        const MaterialApp(
          home: CreateReportScreen(initialStatus: ReportStatus.missing),
        ),
      );
      await tester.pumpAndSettle();

      // Enter required fields
      await tester.enterText(
        find.widgetWithText(
          TextFormField,
          'e.g., MacBook Pro 14 (Space Black)',
        ),
        'Sony WH-1000XM5',
      );
      await tester.enterText(
        find.widgetWithText(
          TextFormField,
          'Describe distinctive markings, color, brand, contents, or serial hints...',
        ),
        'Black over-ear headphones in hard zippered travel case',
      );
      await tester.enterText(
        find.widgetWithText(
          TextFormField,
          'e.g., Espresso Bar on Sagaydachnoho St, Podil',
        ),
        'Terminal 1, Gate B4',
      );

      // Enter negative reward
      final rewardField = find.widgetWithText(
        TextFormField,
        'Enter custom reward amount (optional)',
      );
      await tester.ensureVisible(rewardField);
      await tester.enterText(rewardField, '-50');
      await tester.pumpAndSettle();

      // Tap submit
      final submitButton = find.text('Publish Missing Report');
      await tester.ensureVisible(submitButton);
      await tester.tap(submitButton);
      await tester.pumpAndSettle();

      expect(find.text('Reward cannot be negative.'), findsOneWidget);
    });

    testWidgets(
      'Valid submission creates report in shared repository and pops with confirmation',
      (WidgetTester tester) async {
        final initialCount = ReportRepository.instance.reports.length;

        await tester.binding.setSurfaceSize(const Size(390, 844));
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: Builder(
                builder: (context) => ElevatedButton(
                  onPressed: () {
                    Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => const CreateReportScreen(
                          initialStatus: ReportStatus.missing,
                        ),
                      ),
                    );
                  },
                  child: const Text('Open Create'),
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();

        await tester.tap(find.text('Open Create'));
        await tester.pumpAndSettle();

        // Enter details
        await tester.enterText(
          find.widgetWithText(
            TextFormField,
            'e.g., MacBook Pro 14 (Space Black)',
          ),
          'Fujifilm X-T5',
        );
        await tester.enterText(
          find.widgetWithText(
            TextFormField,
            'Describe distinctive markings, color, brand, contents, or serial hints...',
          ),
          'Silver body with 23mm f/2 lens and brown leather strap',
        );
        await tester.enterText(
          find.widgetWithText(
            TextFormField,
            'e.g., Espresso Bar on Sagaydachnoho St, Podil',
          ),
          'Cafe Yaroslavna, table near bookshelf',
        );

        final rewardField = find.widgetWithText(
          TextFormField,
          'Enter custom reward amount (optional)',
        );
        await tester.ensureVisible(rewardField);
        await tester.enterText(rewardField, '120');
        await tester.pumpAndSettle();

        // Submit
        final submitButton = find.text('Publish Missing Report');
        await tester.ensureVisible(submitButton);
        await tester.tap(submitButton);

        // Verify processing state
        await tester.pump(const Duration(milliseconds: 50));
        expect(find.byType(CircularProgressIndicator), findsOneWidget);

        // Wait for submission to complete and pop
        await tester.pumpAndSettle();

        // Back on root screen
        expect(find.text('Open Create'), findsOneWidget);
        expect(
          find.text('Missing report created: "Fujifilm X-T5".'),
          findsOneWidget,
        );

        // Repository count increased by 1
        expect(
          ReportRepository.instance.reports.length,
          equals(initialCount + 1),
        );
        final created = ReportRepository.instance.reports.first;
        expect(created.title, equals('Fujifilm X-T5'));
        expect(created.reward, equals('\$120'));
        expect(created.status, equals(ReportStatus.missing));
        expect(created.isUserReport, isTrue);
      },
    );
  });

  group('Phase 6.4: End-to-End Navigation & Multi-Screen Shared State Integration', () {
    testWidgets(
      'Full workflow: ChooseReportType -> Create Missing -> Visible on Home, Map, My Reports',
      (WidgetTester tester) async {
        tester.view.physicalSize = const Size(390, 844);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);

        await tester.pumpWidget(const BoomerangApp());
        await tester.pumpAndSettle();

        // 1. From Home screen, tap 'Report Missing' card
        expect(find.text('Report Missing'), findsWidgets);
        await tester.tap(find.text('Report Missing').first);
        await tester.pumpAndSettle();

        // In ChooseReportTypeScreen
        expect(find.byType(ChooseReportTypeScreen), findsOneWidget);
        expect(find.text('Choose Report Type'), findsOneWidget);
        expect(find.text('Report Something Missing'), findsOneWidget);
        expect(find.text('Report Something Found'), findsOneWidget);

        // Tap 'Report Something Missing'
        await tester.tap(find.text('Report Something Missing'));
        await tester.pumpAndSettle();

        // In CreateReportScreen
        expect(find.byType(CreateReportScreen), findsOneWidget);
        expect(find.text('Create Report'), findsOneWidget);

        // Fill in fields
        await tester.enterText(
          find.widgetWithText(
            TextFormField,
            'e.g., MacBook Pro 14 (Space Black)',
          ),
          'Vintage Leica M3',
        );
        await tester.enterText(
          find.widgetWithText(
            TextFormField,
            'Describe distinctive markings, color, brand, contents, or serial hints...',
          ),
          'Chrome finish 35mm rangefinder camera in black leather case',
        );
        await tester.enterText(
          find.widgetWithText(
            TextFormField,
            'e.g., Espresso Bar on Sagaydachnoho St, Podil',
          ),
          'Sophia Square Cafe terrace',
        );

        // Select preset reward '$100'
        final preset100 = find.widgetWithText(OutlinedButton, '\$100');
        await tester.ensureVisible(preset100);
        await tester.tap(preset100);
        await tester.pumpAndSettle();

        // Submit
        final submitBtn = find.text('Publish Missing Report');
        await tester.ensureVisible(submitBtn);
        await tester.tap(submitBtn);

        // Wait for async processing and navigation animation
        await tester.pump(const Duration(milliseconds: 200));
        await tester.pump(const Duration(milliseconds: 300));

        // Confirmation snackbar is shown
        expect(find.textContaining('Missing report created'), findsOneWidget);

        // Dismiss snackbar to prevent hit test interception on bottom UI
        ScaffoldMessenger.of(
          tester.element(find.byType(HomeScreen)),
        ).clearSnackBars();
        await tester.pumpAndSettle();
        expect(find.text('Nearby Reports'), findsOneWidget);

        // 2. Newly created report is in Home feed
        expect(find.text('Vintage Leica M3'), findsOneWidget);

        // 3. Tap on newly created report to open ReportDetailsScreen
        await tester.tap(find.text('Vintage Leica M3'));
        await tester.pumpAndSettle();

        expect(find.byType(ReportDetailsScreen), findsOneWidget);
        expect(find.text('Vintage Leica M3'), findsOneWidget);
        expect(find.text('Sophia Square Cafe terrace'), findsOneWidget);

        // Navigate back to Home
        await tester.tap(
          find.descendant(
            of: find.byType(ReportDetailsScreen),
            matching: find.byIcon(Icons.arrow_back),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.byType(ReportDetailsScreen), findsNothing);

        // 4. Check Map screen
        await tester.tap(find.byKey(const ValueKey('nav_tab_map')));
        await tester.pumpAndSettle();
        expect(find.byType(MapScreen), findsOneWidget);

        // Expand sheet
        await tester.tap(find.text('Expand'));
        await tester.pumpAndSettle();

        // Vintage Leica M3 is present in the Map's nearby report sheet
        expect(find.text('Vintage Leica M3'), findsOneWidget);

        // Collapse sheet
        await tester.tap(find.text('Collapse'));
        await tester.pumpAndSettle();

        // 5. Check Reports tab (My Reports screen)
        await tester.tap(find.byKey(const ValueKey('nav_tab_reports')));
        await tester.pumpAndSettle();
        expect(find.byType(MyReportsScreen), findsOneWidget);

        // Vintage Leica M3 is listed under user reports
        expect(find.text('Vintage Leica M3'), findsOneWidget);
      },
    );

    testWidgets(
      'Full workflow: ChooseReportType -> Create Found (without missing report) -> No Reward',
      (WidgetTester tester) async {
        tester.view.physicalSize = const Size(390, 844);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);

        await tester.pumpWidget(const BoomerangApp());
        await tester.pumpAndSettle();

        // Tap 'Report Found' action card
        expect(find.text('Report Found'), findsWidgets);
        await tester.tap(find.text('Report Found').first);
        await tester.pumpAndSettle();

        // Tap 'Report Something Found'
        await tester.tap(find.text('Report Something Found'));
        await tester.pumpAndSettle();

        // In CreateReportScreen
        expect(find.byType(CreateReportScreen), findsOneWidget);
        // Reward is NOT present
        expect(find.text('Offer a Reward'), findsNothing);

        // Fill in fields
        await tester.enterText(
          find.widgetWithText(
            TextFormField,
            'e.g., MacBook Pro 14 (Space Black)',
          ),
          'Sony Earbuds Case',
        );
        await tester.enterText(
          find.widgetWithText(
            TextFormField,
            'Describe distinctive markings, color, brand, contents, or serial hints...',
          ),
          'Black matte wireless earbuds case with USB-C cable',
        );
        await tester.enterText(
          find.widgetWithText(
            TextFormField,
            'e.g., Espresso Bar on Sagaydachnoho St, Podil',
          ),
          'Subway escalator step 4',
        );

        // Submit
        final submitBtn = find.text('Publish Found Report');
        await tester.ensureVisible(submitBtn);
        await tester.tap(submitBtn);

        // Wait for async processing and navigation animation
        await tester.pump(const Duration(milliseconds: 200));
        await tester.pump(const Duration(milliseconds: 300));

        // Returned to Home with confirmation
        expect(find.textContaining('Found report created'), findsOneWidget);

        await tester.pumpAndSettle();
        expect(find.text('Sony Earbuds Case'), findsOneWidget);

        // Verify in repository: status is found and reward is null
        final created = ReportRepository.instance.reports.first;
        expect(created.title, equals('Sony Earbuds Case'));
        expect(created.status, equals(ReportStatus.found));
        expect(created.reward, isNull);
      },
    );

    testWidgets('Mobile responsive layout test at 360px and 430px viewports', (
      WidgetTester tester,
    ) async {
      for (final width in [360.0, 430.0]) {
        await tester.binding.setSurfaceSize(Size(width, 800));
        await tester.pumpWidget(
          const MaterialApp(
            home: CreateReportScreen(initialStatus: ReportStatus.missing),
          ),
        );
        await tester.pumpAndSettle();

        // Ensure key elements render without any RenderFlex overflow
        expect(find.text('Create Report'), findsOneWidget);
        expect(find.text('Report Missing'), findsOneWidget);
        expect(find.text('Report Found'), findsOneWidget);
        expect(tester.takeException(), isNull);
      }
    });
  });
}
