import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';

enum LocationPermissionStatus {
  unknown,
  serviceDisabled,
  denied,
  deniedForever,
  granted,
  timeout,
  error,
}

class UserLocationData {
  final double latitude;
  final double longitude;
  final double? accuracy;
  final bool isManual;
  final String? label;

  const UserLocationData({
    required this.latitude,
    required this.longitude,
    this.accuracy,
    this.isManual = false,
    this.label,
  });

  LatLng toLatLng() => LatLng(latitude, longitude);

  @override
  String toString() =>
      'UserLocationData(lat: ${latitude.toStringAsFixed(4)}, lon: ${longitude.toStringAsFixed(4)}, manual: $isManual)';
}

class LocationService extends ChangeNotifier {
  static LocationService _instance = LocationService._internal();
  factory LocationService() => _instance;
  LocationService._internal();

  static LocationService get instance => _instance;

  @visibleForTesting
  static void setInstanceForTesting(LocationService service) {
    _instance = service;
  }

  LocationPermissionStatus _status = LocationPermissionStatus.unknown;
  UserLocationData? _currentLocation;
  String? _errorMessage;
  bool _isLoading = false;

  LocationPermissionStatus get status => _status;
  UserLocationData? get currentLocation => _currentLocation;
  String? get errorMessage => _errorMessage;
  bool get isLoading => _isLoading;
  bool get hasLocation => _currentLocation != null;

  /// Check location service and permissions without prompting the user.
  Future<LocationPermissionStatus> checkPermission() async {
    try {
      final isServiceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!isServiceEnabled) {
        _status = LocationPermissionStatus.serviceDisabled;
        _errorMessage = 'Location services are disabled on this device.';
        notifyListeners();
        return _status;
      }

      final permission = await Geolocator.checkPermission();
      _status = _mapPermission(permission);
      _errorMessage = null;
      notifyListeners();
      return _status;
    } catch (e) {
      _status = LocationPermissionStatus.error;
      _errorMessage = 'Failed to verify location permission: $e';
      notifyListeners();
      return _status;
    }
  }

  /// Request location permission from user.
  Future<LocationPermissionStatus> requestPermission() async {
    try {
      final isServiceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!isServiceEnabled) {
        _status = LocationPermissionStatus.serviceDisabled;
        _errorMessage =
            'Location services are disabled. Please enable GPS in device settings.';
        notifyListeners();
        return _status;
      }

      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }

      _status = _mapPermission(permission);
      if (_status == LocationPermissionStatus.denied) {
        _errorMessage =
            'Location permission denied. You can select your position manually on the map.';
      } else if (_status == LocationPermissionStatus.deniedForever) {
        _errorMessage =
            'Location permission permanently denied. Enable in device settings or select manually on map.';
      } else {
        _errorMessage = null;
      }
      notifyListeners();
      return _status;
    } catch (e) {
      _status = LocationPermissionStatus.error;
      _errorMessage = 'Error requesting location permission: $e';
      notifyListeners();
      return _status;
    }
  }

  /// Retrieve current device GPS position after validating permissions.
  Future<UserLocationData?> getCurrentPosition({
    Duration timeout = const Duration(seconds: 10),
  }) async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      final permStatus = await requestPermission();
      if (permStatus != LocationPermissionStatus.granted) {
        _isLoading = false;
        notifyListeners();
        return null;
      }

      final position = await Geolocator.getCurrentPosition(
        locationSettings: LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: timeout,
        ),
      );

      _currentLocation = UserLocationData(
        latitude: position.latitude,
        longitude: position.longitude,
        accuracy: position.accuracy,
        isManual: false,
      );
      _status = LocationPermissionStatus.granted;
      _errorMessage = null;
      _isLoading = false;
      notifyListeners();
      return _currentLocation;
    } on TimeoutException {
      _status = LocationPermissionStatus.timeout;
      _errorMessage =
          'Location request timed out. Please retry or select location on map.';
      _isLoading = false;
      notifyListeners();
      return null;
    } catch (e) {
      _status = LocationPermissionStatus.error;
      _errorMessage = 'Unable to determine device location: $e';
      _isLoading = false;
      notifyListeners();
      return null;
    }
  }

  /// Set manual location fallback when GPS is denied or unavailable.
  void setManualLocation({
    required double latitude,
    required double longitude,
    String? label,
  }) {
    _currentLocation = UserLocationData(
      latitude: latitude,
      longitude: longitude,
      isManual: true,
      label: label ?? 'Custom Selected Point',
    );
    _errorMessage = null;
    notifyListeners();
  }

  /// Clear current location state.
  void clearLocation() {
    _currentLocation = null;
    _errorMessage = null;
    notifyListeners();
  }

  LocationPermissionStatus _mapPermission(LocationPermission permission) {
    switch (permission) {
      case LocationPermission.always:
      case LocationPermission.whileInUse:
        return LocationPermissionStatus.granted;
      case LocationPermission.denied:
        return LocationPermissionStatus.denied;
      case LocationPermission.deniedForever:
        return LocationPermissionStatus.deniedForever;
      case LocationPermission.unableToDetermine:
        return LocationPermissionStatus.unknown;
    }
  }
}
