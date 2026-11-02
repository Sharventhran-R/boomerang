import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/models/match_model.dart';
import 'package:frontend/models/report_model.dart';
import 'package:frontend/services/match_repository.dart';
import 'package:frontend/services/report_repository.dart';
import 'package:frontend/theme.dart';
import 'package:frontend/ui/screens/match_detail_screen.dart';
import 'package:frontend/ui/screens/report_details_screen.dart';
import 'package:frontend/ui/widgets/match_card.dart';
import 'package:frontend/ui/widgets/status_label.dart';

void main() {
  group('Phase 8.6 - Match Models', () {
    test('MatchModel deserializes correctly from backend JSON', () {
      final json = {
        'id': 'match-uuid-1',
        'report_missing_id': 'missing-uuid-1',
        'report_found_id': 'found-uuid-1',
        'status': 'ACTIVE',
        'composite_score': 87.6,
        'score_identity': 90.0,
        'score_characteristics': 85.0,
        'score_distance': 92.0,
        'score_time': 80.0,
        'classification': 'HIGH_PRIORITY',
        'alert_eligible': true,
        'evidence_summary': 'Strong brand & physical trait overlap',
        'opposite_report': {
          'id': 'found-uuid-1',
          'type': 'FOUND',
          'title': 'Found Space Black iPhone',
          'description': 'Near park bench with case',
          'category': 'ELECTRONICS',
          'latitude': 40.785,
          'longitude': -73.968,
          'event_time': '2026-10-14T12:00:00Z',
          'reward_amount': null,
          'status': 'ACTIVE',
          'created_at': '2026-10-14T12:05:00Z',
          'distance_km': 0.45,
          'images': [],
        },
        'created_at': '2026-10-14T12:10:00Z',
        'last_scored_at': '2026-10-14T12:10:00Z',
      };

      final match = MatchModel.fromJson(json);

      expect(match.id, 'match-uuid-1');
      expect(match.reportMissingId, 'missing-uuid-1');
      expect(match.reportFoundId, 'found-uuid-1');
      expect(match.status, 'ACTIVE');
      expect(match.compositeScore, 87.6);
      expect(match.scorePercentage, 88);
      expect(match.classification, 'HIGH_PRIORITY');
      expect(match.formattedClassification, 'High Priority');
      expect(match.alertEligible, isTrue);
      expect(match.oppositeReport.title, 'Found Space Black iPhone');
      expect(match.oppositeReport.isFound, isTrue);
    });

    test('MatchDetailModel deserializes correctly from backend JSON', () {
      final json = {
        'id': 'match-uuid-2',
        'status': 'ACTIVE',
        'composite_score': 92.4,
        'raw_composite_score': 92.4,
        'contradiction_penalty': 0.0,
        'score_identity': 95.0,
        'score_characteristics': 90.0,
        'score_distance': 94.0,
        'score_time': 90.0,
        'classification': 'HIGH_PRIORITY',
        'alert_eligible': true,
        'minimum_evidence_satisfied': true,
        'evidence_summary': 'Exact brand, model, and scratch marks',
        'explainability_details': {
          'identity': {
            'matched_brand': 'Apple',
            'matched_model': 'iPhone 15 Pro',
            'category_score': 40.0,
            'brand_model_score': 35.0,
          },
          'characteristics': {
            'matched_colors': ['black'],
            'matched_cases': ['silicone'],
            'matched_distinctive_marks': ['screen hairline'],
            'conflicting_colors': [],
            'has_contradiction': false,
          },
          'distance': {'distance_meters': 320.0, 'distance_km': 0.32},
          'time': {'delta_hours': 3.5, 'delta_days': 0.15},
        },
        'scoring_version': 1,
        'last_scored_at': '2026-10-14T12:10:00Z',
        'created_at': '2026-10-14T12:10:00Z',
        'updated_at': '2026-10-14T12:10:00Z',
        'report_missing': {
          'id': 'missing-uuid-2',
          'type': 'MISSING',
          'title': 'My Lost iPhone',
          'description': 'Left on bench',
          'category': 'ELECTRONICS',
          'latitude': 40.785,
          'longitude': -73.968,
          'event_time': '2026-10-14T10:00:00Z',
          'reward_amount': '100.00',
          'status': 'ACTIVE',
          'created_at': '2026-10-14T10:05:00Z',
          'distance_km': 0.32,
          'images': [],
        },
        'report_found': {
          'id': 'found-uuid-2',
          'type': 'FOUND',
          'title': 'Found iPhone by Fountain',
          'description': 'Black iPhone in silicone sleeve',
          'category': 'ELECTRONICS',
          'latitude': 40.786,
          'longitude': -73.967,
          'event_time': '2026-10-14T13:30:00Z',
          'reward_amount': null,
          'status': 'ACTIVE',
          'created_at': '2026-10-14T13:35:00Z',
          'distance_km': 0.32,
          'images': [],
        },
        'user_role': 'MISSING',
      };

      final detail = MatchDetailModel.fromJson(json);

      expect(detail.id, 'match-uuid-2');
      expect(detail.userRole, 'MISSING');
      expect(detail.scorePercentage, 92);
      expect(detail.reportMissing.title, 'My Lost iPhone');
      expect(detail.reportFound.title, 'Found iPhone by Fountain');
      expect(
        detail.explainabilityDetails['identity']['matched_brand'],
        'Apple',
      );
      expect(detail.explainabilityDetails['distance']['distance_km'], 0.32);
    });
  });

  group('Phase 8.6 - MatchCard Widget', () {
    testWidgets('renders score badge, title, and handles tap', (tester) async {
      bool tapped = false;
      final match = MatchModel(
        id: 'test-match-1',
        reportMissingId: 'mis-1',
        reportFoundId: 'fnd-1',
        status: 'ACTIVE',
        compositeScore: 91.0,
        scoreIdentity: 90.0,
        scoreCharacteristics: 85.0,
        scoreDistance: 95.0,
        scoreTime: 92.0,
        classification: 'HIGH_PRIORITY',
        alertEligible: true,
        evidenceSummary: 'Silicon case and corner scratch match.',
        oppositeReport: ReportModel(
          id: 'fnd-1',
          title: 'Discovered Black Wallet',
          category: 'Wallet',
          description: 'Leather bi-fold',
          locationDescription: 'Sector [40.75, -73.98]',
          dateTime: DateTime.now(),
          status: ReportStatus.found,
          distance: '0.2 km away',
        ),
        createdAt: DateTime.now(),
        lastScoredAt: DateTime.now(),
      );

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: Scaffold(
            body: MatchCard(match: match, onTap: () => tapped = true),
          ),
        ),
      );

      expect(find.text('91% MATCH'), findsOneWidget);
      expect(find.text('HIGH PRIORITY'), findsOneWidget);
      expect(find.text('Discovered Black Wallet'), findsOneWidget);
      expect(
        find.text('Silicon case and corner scratch match.'),
        findsOneWidget,
      );

      await tester.tap(find.byType(MatchCard));
      await tester.pumpAndSettle();
      expect(tapped, isTrue);
    });
  });

  group('Phase 8.6 - MatchDetailScreen Widget', () {
    testWidgets('renders composite score, signal cards, and telemetry rows', (
      tester,
    ) async {
      final detail = MatchDetailModel(
        id: 'detail-test-1',
        status: 'ACTIVE',
        compositeScore: 89.0,
        rawCompositeScore: 89.0,
        contradictionPenalty: 0.0,
        scoreIdentity: 92.0,
        scoreCharacteristics: 88.0,
        scoreDistance: 90.0,
        scoreTime: 86.0,
        classification: 'HIGH_PRIORITY',
        alertEligible: true,
        minimumEvidenceSatisfied: true,
        evidenceSummary: 'Confirmed brand token overlap and identical color.',
        explainabilityDetails: {
          'identity': {
            'matched_brand': 'Sony',
            'matched_model': 'WH-1000XM5',
            'category_score': 40.0,
          },
          'characteristics': {
            'matched_colors': ['silver'],
            'matched_cases': ['hard shell'],
            'conflicting_colors': [],
            'has_contradiction': false,
          },
          'distance': {'distance_meters': 410.0, 'distance_km': 0.41},
          'time': {'delta_hours': 5.2, 'delta_days': 0.2},
        },
        scoringVersion: 1,
        lastScoredAt: DateTime.now(),
        createdAt: DateTime.now(),
        updatedAt: DateTime.now(),
        reportMissing: ReportModel(
          id: 'mis-test',
          title: 'Lost Sony Headphones',
          category: 'Electronics',
          description: 'Silver over-ear headphones',
          locationDescription: 'Coffee shop downtown',
          dateTime: DateTime.now(),
          status: ReportStatus.missing,
        ),
        reportFound: ReportModel(
          id: 'fnd-test',
          title: 'Found Silver Sony Headset',
          category: 'Electronics',
          description: 'In hard case left on table',
          locationDescription: 'Downtown espresso cafe',
          dateTime: DateTime.now(),
          status: ReportStatus.found,
        ),
        userRole: 'MISSING',
      );

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: MatchDetailScreen(
            matchId: 'detail-test-1',
            initialMatch: detail,
          ),
        ),
      );

      // Verify Header & Hero
      expect(find.text('Match Telemetry'), findsOneWidget);
      expect(find.text('89%'), findsOneWidget);
      expect(find.text('COMPOSITE MATCH SCORE'), findsOneWidget);
      expect(find.text('HIGH PRIORITY'), findsOneWidget);
      expect(find.text('ALERT ELIGIBLE'), findsOneWidget);

      // Verify Evidence Summary
      expect(
        find.text('Confirmed brand token overlap and identical color.'),
        findsOneWidget,
      );

      // Verify Reports
      expect(find.text('Lost Sony Headphones'), findsOneWidget);
      expect(find.text('Found Silver Sony Headset'), findsOneWidget);

      // Verify the 4 signals
      expect(find.text('SIGNAL I'), findsOneWidget);
      expect(find.text('Item Identity'), findsOneWidget);
      expect(find.text('SIGNAL C'), findsOneWidget);
      expect(find.text('Physical Characteristics'), findsOneWidget);
      expect(find.text('SIGNAL D'), findsOneWidget);
      expect(find.text('Geographic Distance'), findsOneWidget);
      expect(find.text('SIGNAL T'), findsOneWidget);
      expect(find.text('Temporal Compatibility'), findsOneWidget);

      // Verify Telemetry Rows
      expect(find.text('Matched Brand'), findsOneWidget);
      expect(find.text('Sony'), findsOneWidget);
      expect(find.text('Matched Colors'), findsOneWidget);
      expect(find.text('silver'), findsOneWidget);
      expect(find.text('Spatial Proximity'), findsOneWidget);
      expect(find.text('0.41 km'), findsOneWidget);

      // Verify Action Button for missing report owner
      expect(find.text('Initiate Recovery Contact'), findsOneWidget);
    });
  });

  group('Phase 8.6 - ReportDetailsScreen Potential Matches Integration', () {
    testWidgets('renders potential matches section when matches are present', (
      tester,
    ) async {
      ReportRepository.instance.resetToDefault();
      final mockRepo = MatchRepository.instance;
      mockRepo.configure(isMockMode: true);

      final dummyMatch = MatchModel(
        id: 'm-dummy',
        reportMissingId: 'REP-001',
        reportFoundId: 'rep-opp',
        status: 'ACTIVE',
        compositeScore: 94.0,
        scoreIdentity: 95.0,
        scoreCharacteristics: 90.0,
        scoreDistance: 95.0,
        scoreTime: 96.0,
        classification: 'HIGH_PRIORITY',
        alertEligible: true,
        evidenceSummary: 'Direct match for black leather wallet with keys',
        oppositeReport: ReportModel(
          id: 'rep-opp',
          title: 'Found Black Leather Wallet',
          category: 'Wallet',
          description: 'Found near metro exit',
          locationDescription: 'Metro entrance',
          dateTime: DateTime.now(),
          status: ReportStatus.found,
          distance: '0.1 km away',
        ),
        createdAt: DateTime.now(),
        lastScoredAt: DateTime.now(),
      );

      mockRepo.setMockMatches('REP-001', [dummyMatch]);

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: const ReportDetailsScreen(
            reportId: 'REP-001',
            title: 'MacBook Pro 14',
            category: 'Electronics',
            description: 'My lost laptop',
            status: ReportStatus.missing,
          ),
        ),
      );

      // Let report and matches load
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));

      // Verify Potential Matches header and card
      expect(find.text('POTENTIAL MATCHES'), findsOneWidget);
      expect(find.text('94% MATCH'), findsOneWidget);
      expect(find.text('Found Black Leather Wallet'), findsOneWidget);
    });
  });
}
