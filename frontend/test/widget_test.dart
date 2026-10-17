import 'package:flutter_test/flutter_test.dart';

import 'package:frontend/main.dart';

void main() {
  testWidgets('Boomerang Phase 6.3 smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(const BoomerangApp());

    // Should start on Home
    expect(find.text('Nearby Reports'), findsOneWidget); // Found on home screen
    expect(find.text('Map View'), findsOneWidget);

    // Test navigation to Map
    await tester.tap(find.text('Map'));
    await tester.pumpAndSettle();

    // Should see map screen elements
    expect(find.text('Select Location'), findsOneWidget);

    // Bottom sheet text
    expect(find.text('18 items'), findsOneWidget);
  });
}
