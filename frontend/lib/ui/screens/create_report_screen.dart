import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import '../../models/report_model.dart';
import '../../services/api_client.dart';
import '../../services/location_service.dart';
import '../../services/map_config.dart';
import '../../services/report_repository.dart';
import '../../theme.dart';
import '../widgets/app_toast.dart';
import '../widgets/status_label.dart';
import 'report_details_screen.dart';

class CreateReportScreen extends StatefulWidget {
  final ReportStatus initialStatus;
  final ValueChanged<ReportModel>? onReportCreated;

  const CreateReportScreen({
    super.key,
    this.initialStatus = ReportStatus.missing,
    this.onReportCreated,
  });

  @override
  State<CreateReportScreen> createState() => _CreateReportScreenState();
}

class _CreateReportScreenState extends State<CreateReportScreen> {
  final _formKey = GlobalKey<FormState>();

  late ReportStatus _status;
  final TextEditingController _titleController = TextEditingController();
  final TextEditingController _descriptionController = TextEditingController();
  final TextEditingController _locationController = TextEditingController();
  final TextEditingController _rewardController = TextEditingController();
  final TextEditingController _latitudeController = TextEditingController();
  final TextEditingController _longitudeController = TextEditingController();

  String _selectedCategory = 'Electronics';
  DateTime _selectedDate = DateTime.now();
  TimeOfDay _selectedTime = TimeOfDay.now();
  final List<String> _attachedPhotos = [];
  bool _isSubmitting = false;

  final List<String> _categories = const [
    'Electronics',
    'Documents',
    'Wallet',
    'Bag',
    'Keys',
    'Pet',
    'Jewelry',
    'Other',
  ];

  final List<String> _samplePhotos = const [
    'https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=400&q=80',
    'https://images.unsplash.com/photo-1627123424574-724758594e93?w=400&q=80',
    'https://images.unsplash.com/photo-1584917865442-de89df76afd3?w=400&q=80',
    'https://images.unsplash.com/photo-1543466835-00a7907e9de1?w=400&q=80',
  ];

  @override
  void initState() {
    super.initState();
    _status = widget.initialStatus;
  }

  @override
  void dispose() {
    _titleController.dispose();
    _descriptionController.dispose();
    _locationController.dispose();
    _rewardController.dispose();
    _latitudeController.dispose();
    _longitudeController.dispose();
    super.dispose();
  }

  void _onStatusChanged(ReportStatus newStatus) {
    if (_status == newStatus) return;
    setState(() {
      _status = newStatus;
      // Enforce business rule: when switching to FOUND, reward field is hidden and cleared
      if (_status == ReportStatus.found) {
        _rewardController.clear();
      }
    });
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _selectedDate,
      firstDate: DateTime.now().subtract(const Duration(days: 365)),
      lastDate: DateTime.now().add(const Duration(days: 1)),
      builder: (context, child) {
        return Theme(
          data: Theme.of(context).copyWith(
            colorScheme: const ColorScheme.dark(
              primary: AppTheme.actionPrimary,
              onPrimary: AppTheme.onActionPrimary,
              surface: AppTheme.card,
              onSurface: AppTheme.primaryText,
            ),
          ),
          child: child!,
        );
      },
    );
    if (picked != null) {
      setState(() => _selectedDate = picked);
    }
  }

  Future<void> _pickTime() async {
    final picked = await showTimePicker(
      context: context,
      initialTime: _selectedTime,
      builder: (context, child) {
        return Theme(
          data: Theme.of(context).copyWith(
            colorScheme: const ColorScheme.dark(
              primary: AppTheme.actionPrimary,
              onPrimary: AppTheme.onActionPrimary,
              surface: AppTheme.card,
              onSurface: AppTheme.primaryText,
            ),
          ),
          child: child!,
        );
      },
    );
    if (picked != null) {
      setState(() => _selectedTime = picked);
    }
  }

  void _showAddPhotoSheet() {
    if (_attachedPhotos.length >= 5) {
      AppToast.info(context, message: 'Maximum 5 photos allowed per report.');
      return;
    }

    showModalBottomSheet(
      context: context,
      backgroundColor: AppTheme.card,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
        side: BorderSide(color: AppTheme.borderSubtle),
      ),
      builder: (ctx) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'Attach Photo',
                      style: TextStyle(
                        fontFamily: 'Hanken Grotesk',
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.primaryText,
                      ),
                    ),
                    IconButton(
                      icon: const Icon(
                        Icons.close,
                        color: AppTheme.secondaryText,
                        size: 20,
                      ),
                      onPressed: () => Navigator.pop(ctx),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                const Text(
                  'Select a sample item photo or attach an image slot (In-memory mock preview).',
                  style: TextStyle(color: AppTheme.secondaryText, fontSize: 12),
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.surface,
                          foregroundColor: AppTheme.primaryText,
                          side: const BorderSide(color: AppTheme.borderMuted),
                          padding: const EdgeInsets.symmetric(vertical: 12),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                          ),
                        ),
                        icon: const Icon(Icons.camera_alt, size: 18),
                        label: const Text('Capture (Mock)'),
                        onPressed: () {
                          Navigator.pop(ctx);
                          _addPhoto(
                            _samplePhotos[_attachedPhotos.length %
                                _samplePhotos.length],
                          );
                        },
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.actionPrimary,
                          foregroundColor: AppTheme.onActionPrimary,
                          padding: const EdgeInsets.symmetric(vertical: 12),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                          ),
                        ),
                        icon: const Icon(Icons.photo_library, size: 18),
                        label: const Text('From Gallery'),
                        onPressed: () {
                          Navigator.pop(ctx);
                          _addPhoto(
                            _samplePhotos[(_attachedPhotos.length + 1) %
                                _samplePhotos.length],
                          );
                        },
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
              ],
            ),
          ),
        );
      },
    );
  }

  void _addPhoto(String url) {
    setState(() {
      _attachedPhotos.add(url);
    });
    AppToast.info(
      context,
      message: 'Photo ${_attachedPhotos.length} of 5 attached.',
    );
  }

  void _removePhoto(int index) {
    setState(() {
      _attachedPhotos.removeAt(index);
    });
  }

  Future<void> _submitReport() async {
    if (_isSubmitting) return;

    if (!_formKey.currentState!.validate()) {
      AppToast.error(
        context,
        message: 'Please correct the highlighted fields before submitting.',
      );
      return;
    }

    setState(() => _isSubmitting = true);

    try {
      final combinedDateTime = DateTime(
        _selectedDate.year,
        _selectedDate.month,
        _selectedDate.day,
        _selectedTime.hour,
        _selectedTime.minute,
      );

      final latStr = _latitudeController.text.trim();
      final lonStr = _longitudeController.text.trim();
      double? lat = double.tryParse(latStr);
      double? lon = double.tryParse(lonStr);

      if (lat == null || lon == null) {
        if (LocationService.instance.currentLocation != null) {
          lat = LocationService.instance.currentLocation!.latitude;
          lon = LocationService.instance.currentLocation!.longitude;
        } else if (ReportRepository.instance.isMockMode) {
          lat = 50.4501;
          lon = 30.5234;
        }
      }

      if (lat == null || lon == null) {
        AppToast.error(
          context,
          message:
              'Please specify coordinates using GPS, Pick on Map, or manual entry.',
        );
        setState(() => _isSubmitting = false);
        return;
      }

      final created = await ReportRepository.instance.createReport(
        title: _titleController.text,
        category: _selectedCategory,
        description: _descriptionController.text,
        locationDescription: _locationController.text,
        dateTime: combinedDateTime,
        status: _status,
        reward: _status == ReportStatus.missing ? _rewardController.text : null,
        latitude: lat,
        longitude: lon,
        photos: _attachedPhotos,
      );

      if (!mounted) return;

      widget.onReportCreated?.call(created);

      final nav = Navigator.of(context);

      // Return to previous screen or main nav first
      nav.pop(true);

      AppToast.success(
        context,
        message:
            '${_status == ReportStatus.missing ? "Missing" : "Found"} report created: "${created.title}".',
        actionLabel: 'VIEW',
        onAction: () {
          nav.push(
            MaterialPageRoute(
              builder: (_) => ReportDetailsScreen(
                reportId: created.id,
                title: created.title,
                category: created.category,
                distance: created.distance,
                timeAgo: created.timeAgo,
                status: created.status,
                reward: created.reward,
                description: created.description,
                locationDescription: created.locationDescription,
              ),
            ),
          );
        },
      );
    } catch (e) {
      if (mounted) {
        final errText = e is ApiException
            ? e.message
            : (e is NetworkException ? e.message : 'Error creating report: $e');
        AppToast.error(context, message: errText);
      }
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final isMissing = _status == ReportStatus.missing;

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        backgroundColor: AppTheme.card,
        elevation: 0,
        leading: Tooltip(
          message: 'Back',
          child: IconButton(
            icon: const Icon(Icons.arrow_back, color: AppTheme.primaryText),
            tooltip: 'Back',
            onPressed: () => Navigator.of(context).pop(),
          ),
        ),
        title: const Text(
          'Create Report',
          style: TextStyle(
            color: AppTheme.primaryText,
            fontWeight: FontWeight.w600,
            fontSize: 16,
          ),
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Center(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: AppTheme.surface,
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: const Text(
                  'STEP 2 OF 2',
                  style: TextStyle(
                    fontSize: 9.5,
                    fontWeight: FontWeight.bold,
                    color: AppTheme.secondaryText,
                    letterSpacing: 0.8,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 600),
            child: Form(
              key: _formKey,
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Segmented Report Type Switcher
                    _buildTypeSwitcher(isMissing),
                    const SizedBox(height: 16),

                    // Photos Attachment Section
                    _buildPhotoSection(),
                    const SizedBox(height: 16),

                    // Item Details Section
                    _buildItemDetailsSection(),
                    const SizedBox(height: 16),

                    // When & Where Section
                    _buildWhenWhereSection(isMissing),
                    const SizedBox(height: 16),

                    // Reward Section (Only for MISSING reports)
                    if (isMissing) ...[
                      _buildRewardSection(),
                      const SizedBox(height: 16),
                    ],

                    // Submission Area
                    _buildSubmissionActions(isMissing),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildTypeSwitcher(bool isMissing) {
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.card,
        borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
        border: Border.all(color: AppTheme.borderSubtle),
      ),
      padding: const EdgeInsets.all(4),
      child: Row(
        children: [
          Expanded(
            child: Semantics(
              button: true,
              selected: isMissing,
              label: 'Select Report Missing type',
              child: InkWell(
                onTap: () => _onStatusChanged(ReportStatus.missing),
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  decoration: BoxDecoration(
                    color: isMissing
                        ? AppTheme.highlightSurface
                        : Colors.transparent,
                    borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                    border: Border.all(
                      color: isMissing
                          ? AppTheme.primaryText
                          : Colors.transparent,
                    ),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        Icons.priority_high,
                        size: 14,
                        color: isMissing
                            ? AppTheme.primaryText
                            : AppTheme.secondaryText,
                      ),
                      const SizedBox(width: 6),
                      Flexible(
                        child: Text(
                          'Report Missing',
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: isMissing
                                ? FontWeight.bold
                                : FontWeight.w500,
                            color: isMissing
                                ? AppTheme.primaryText
                                : AppTheme.secondaryText,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: Semantics(
              button: true,
              selected: !isMissing,
              label: 'Select Report Found type',
              child: InkWell(
                onTap: () => _onStatusChanged(ReportStatus.found),
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  decoration: BoxDecoration(
                    color: !isMissing
                        ? AppTheme.highlightSurface
                        : Colors.transparent,
                    borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                    border: Border.all(
                      color: !isMissing
                          ? AppTheme.primaryText
                          : Colors.transparent,
                    ),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        Icons.check,
                        size: 14,
                        color: !isMissing
                            ? AppTheme.primaryText
                            : AppTheme.secondaryText,
                      ),
                      const SizedBox(width: 6),
                      Flexible(
                        child: Text(
                          'Report Found',
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: !isMissing
                                ? FontWeight.bold
                                : FontWeight.w500,
                            color: !isMissing
                                ? AppTheme.primaryText
                                : AppTheme.secondaryText,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPhotoSection() {
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.card,
        borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
        border: Border.all(color: AppTheme.borderSubtle),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Expanded(
                child: Row(
                  children: [
                    Icon(
                      Icons.add_a_photo,
                      size: 16,
                      color: AppTheme.primaryText,
                    ),
                    SizedBox(width: 8),
                    Flexible(
                      child: Text(
                        'Item Photos',
                        style: TextStyle(
                          fontFamily: 'Hanken Grotesk',
                          fontSize: 14,
                          fontWeight: FontWeight.bold,
                          color: AppTheme.primaryText,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Text(
                '${_attachedPhotos.length} of 5 added',
                style: const TextStyle(
                  fontSize: 11,
                  color: AppTheme.secondaryText,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          const Text(
            'Clear shots of scratches, logos, or unique marks help community members recognize the item quickly.',
            style: TextStyle(
              fontSize: 11.5,
              color: AppTheme.secondaryText,
              height: 1.3,
            ),
          ),
          const SizedBox(height: 12),

          // Photo grid row
          SizedBox(
            height: 80,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: _attachedPhotos.length + 1,
              separatorBuilder: (context, index) => const SizedBox(width: 8),
              itemBuilder: (context, index) {
                if (index < _attachedPhotos.length) {
                  return Stack(
                    children: [
                      Container(
                        width: 80,
                        height: 80,
                        decoration: BoxDecoration(
                          color: AppTheme.surface,
                          borderRadius: BorderRadius.circular(
                            AppTheme.smallRadius,
                          ),
                          border: Border.all(color: AppTheme.borderMuted),
                        ),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(
                            AppTheme.smallRadius,
                          ),
                          child: Container(
                            color: AppTheme.elevatedSurface,
                            child: const Center(
                              child: Icon(
                                Icons.image,
                                color: AppTheme.secondaryText,
                                size: 28,
                              ),
                            ),
                          ),
                        ),
                      ),
                      if (index == 0)
                        Positioned(
                          bottom: 4,
                          left: 4,
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 4,
                              vertical: 1,
                            ),
                            decoration: BoxDecoration(
                              color: Colors.black87,
                              borderRadius: BorderRadius.circular(2),
                            ),
                            child: const Text(
                              'MAIN',
                              style: TextStyle(
                                fontSize: 8,
                                fontWeight: FontWeight.bold,
                                color: AppTheme.primaryText,
                              ),
                            ),
                          ),
                        ),
                      Positioned(
                        top: 2,
                        right: 2,
                        child: Semantics(
                          button: true,
                          label: 'Remove photo ${index + 1}',
                          child: InkWell(
                            onTap: () => _removePhoto(index),
                            child: Container(
                              padding: const EdgeInsets.all(2),
                              decoration: const BoxDecoration(
                                color: Colors.black87,
                                shape: BoxShape.circle,
                              ),
                              child: const Icon(
                                Icons.close,
                                size: 14,
                                color: AppTheme.primaryText,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ],
                  );
                }

                // Add button slot
                return Semantics(
                  button: true,
                  label: 'Add photo',
                  child: InkWell(
                    onTap: _showAddPhotoSheet,
                    borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                    child: Container(
                      width: 80,
                      height: 80,
                      decoration: BoxDecoration(
                        color: AppTheme.surface,
                        borderRadius: BorderRadius.circular(
                          AppTheme.smallRadius,
                        ),
                        border: Border.all(
                          color: AppTheme.borderSubtle,
                          style: BorderStyle.solid,
                        ),
                      ),
                      child: const Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(
                            Icons.add,
                            size: 20,
                            color: AppTheme.primaryText,
                          ),
                          SizedBox(height: 4),
                          Text(
                            'Add photo',
                            style: TextStyle(
                              fontSize: 9.5,
                              color: AppTheme.secondaryText,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildItemDetailsSection() {
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.card,
        borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
        border: Border.all(color: AppTheme.borderSubtle),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.label_outline, size: 16, color: AppTheme.primaryText),
              SizedBox(width: 8),
              Text(
                'Item Details',
                style: TextStyle(
                  fontFamily: 'Hanken Grotesk',
                  fontSize: 14,
                  fontWeight: FontWeight.bold,
                  color: AppTheme.primaryText,
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // Title
          const Text(
            'Item Title *',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppTheme.secondaryText,
            ),
          ),
          const SizedBox(height: 6),
          TextFormField(
            controller: _titleController,
            style: const TextStyle(color: AppTheme.primaryText, fontSize: 13.5),
            decoration: InputDecoration(
              hintText: 'e.g., MacBook Pro 14 (Space Black)',
              hintStyle: const TextStyle(
                color: AppTheme.mutedText,
                fontSize: 13,
              ),
              filled: true,
              fillColor: AppTheme.surface,
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 12,
                vertical: 12,
              ),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderSubtle),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderSubtle),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderHighlight),
              ),
            ),
            validator: (val) {
              if (val == null || val.trim().isEmpty) {
                return 'Please enter an item title.';
              }
              if (val.trim().length < 3) {
                return 'Title must be at least 3 characters.';
              }
              return null;
            },
          ),
          const SizedBox(height: 14),

          // Category
          const Text(
            'Category *',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppTheme.secondaryText,
            ),
          ),
          const SizedBox(height: 8),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: _categories.map((cat) {
                final isSelected = _selectedCategory == cat;
                return Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: Semantics(
                    button: true,
                    selected: isSelected,
                    label: 'Category $cat',
                    child: ChoiceChip(
                      label: Text(cat),
                      selected: isSelected,
                      onSelected: (selected) {
                        if (selected) setState(() => _selectedCategory = cat);
                      },
                      labelStyle: TextStyle(
                        fontSize: 11,
                        fontWeight: isSelected
                            ? FontWeight.bold
                            : FontWeight.w500,
                        color: isSelected
                            ? AppTheme.onActionPrimary
                            : AppTheme.secondaryText,
                      ),
                      backgroundColor: AppTheme.surface,
                      selectedColor: AppTheme.actionPrimary,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(
                          AppTheme.smallRadius,
                        ),
                        side: BorderSide(
                          color: isSelected
                              ? AppTheme.actionPrimary
                              : AppTheme.borderSubtle,
                        ),
                      ),
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 14),

          // Description
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'Description *',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.secondaryText,
                ),
              ),
              ValueListenableBuilder<TextEditingValue>(
                valueListenable: _descriptionController,
                builder: (context, val, child) => Text(
                  '${val.text.length} / 500',
                  style: const TextStyle(
                    fontSize: 10,
                    color: AppTheme.mutedText,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          TextFormField(
            controller: _descriptionController,
            maxLines: 4,
            maxLength: 500,
            style: const TextStyle(color: AppTheme.primaryText, fontSize: 13),
            decoration: InputDecoration(
              counterText: '',
              hintText:
                  'Describe distinctive markings, color, brand, contents, or serial hints...',
              hintStyle: const TextStyle(
                color: AppTheme.mutedText,
                fontSize: 12.5,
              ),
              filled: true,
              fillColor: AppTheme.surface,
              contentPadding: const EdgeInsets.all(12),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderSubtle),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderSubtle),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderHighlight),
              ),
            ),
            validator: (val) {
              if (val == null || val.trim().isEmpty) {
                return 'Please enter a description.';
              }
              if (val.trim().length < 10) {
                return 'Description must be at least 10 characters.';
              }
              return null;
            },
          ),
        ],
      ),
    );
  }

  Widget _buildWhenWhereSection(bool isMissing) {
    final dateStr =
        '${_selectedDate.year}-${_selectedDate.month.toString().padLeft(2, '0')}-${_selectedDate.day.toString().padLeft(2, '0')}';
    final timeStr = _selectedTime.format(context);

    return Container(
      decoration: BoxDecoration(
        color: AppTheme.card,
        borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
        border: Border.all(color: AppTheme.borderSubtle),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.schedule, size: 16, color: AppTheme.primaryText),
              const SizedBox(width: 8),
              Text(
                isMissing ? 'When & Where Lost' : 'When & Where Found',
                style: const TextStyle(
                  fontFamily: 'Hanken Grotesk',
                  fontSize: 14,
                  fontWeight: FontWeight.bold,
                  color: AppTheme.primaryText,
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // Date & Time pickers
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      isMissing ? 'Date Lost *' : 'Date Found *',
                      style: const TextStyle(
                        fontSize: 11.5,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.secondaryText,
                      ),
                    ),
                    const SizedBox(height: 6),
                    InkWell(
                      onTap: _pickDate,
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 11,
                        ),
                        decoration: BoxDecoration(
                          color: AppTheme.surface,
                          borderRadius: BorderRadius.circular(
                            AppTheme.smallRadius,
                          ),
                          border: Border.all(color: AppTheme.borderSubtle),
                        ),
                        child: Row(
                          children: [
                            const Icon(
                              Icons.calendar_today,
                              size: 14,
                              color: AppTheme.secondaryText,
                            ),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Text(
                                dateStr,
                                style: const TextStyle(
                                  fontSize: 12.5,
                                  color: AppTheme.primaryText,
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Approx. Time *',
                      style: TextStyle(
                        fontSize: 11.5,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.secondaryText,
                      ),
                    ),
                    const SizedBox(height: 6),
                    InkWell(
                      onTap: _pickTime,
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 11,
                        ),
                        decoration: BoxDecoration(
                          color: AppTheme.surface,
                          borderRadius: BorderRadius.circular(
                            AppTheme.smallRadius,
                          ),
                          border: Border.all(color: AppTheme.borderSubtle),
                        ),
                        child: Row(
                          children: [
                            const Icon(
                              Icons.access_time,
                              size: 14,
                              color: AppTheme.secondaryText,
                            ),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Text(
                                timeStr,
                                style: const TextStyle(
                                  fontSize: 12.5,
                                  color: AppTheme.primaryText,
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // Location field
          Text(
            isMissing ? 'Last Seen Location *' : 'Discovery Location *',
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppTheme.secondaryText,
            ),
          ),
          const SizedBox(height: 6),
          TextFormField(
            controller: _locationController,
            style: const TextStyle(color: AppTheme.primaryText, fontSize: 13),
            decoration: InputDecoration(
              hintText: 'e.g., Espresso Bar on Sagaydachnoho St, Podil',
              hintStyle: const TextStyle(
                color: AppTheme.mutedText,
                fontSize: 12.5,
              ),
              filled: true,
              fillColor: AppTheme.surface,
              prefixIcon: const Icon(
                Icons.location_on,
                size: 18,
                color: AppTheme.secondaryText,
              ),
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 12,
                vertical: 12,
              ),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderSubtle),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderSubtle),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderHighlight),
              ),
            ),
            validator: (val) {
              if (val == null || val.trim().isEmpty) {
                return 'Please enter a location.';
              }
              return null;
            },
          ),
          const SizedBox(height: 8),

          // GPS Location and Map Picker quick actions
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _isLocatingGps ? null : _useGpsLocation,
                  icon: _isLocatingGps
                      ? const SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: AppTheme.primaryText,
                          ),
                        )
                      : const Icon(Icons.my_location, size: 14),
                  label: const Text(
                    'Use GPS',
                    style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
                  ),
                  style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: AppTheme.borderSubtle),
                    foregroundColor: AppTheme.primaryText,
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _openMapLocationPicker,
                  icon: const Icon(Icons.map_outlined, size: 14),
                  label: const Text(
                    'Pick on Map',
                    style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
                  ),
                  style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: AppTheme.borderSubtle),
                    foregroundColor: AppTheme.primaryText,
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                    ),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),

          // Monochromatic manual coordinate inputs
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Latitude *',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.secondaryText,
                      ),
                    ),
                    const SizedBox(height: 4),
                    TextFormField(
                      key: const Key('create_report_latitude_field'),
                      controller: _latitudeController,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                        signed: true,
                      ),
                      style: const TextStyle(
                        color: AppTheme.primaryText,
                        fontSize: 12,
                      ),
                      decoration: InputDecoration(
                        hintText: 'e.g. 51.5074',
                        filled: true,
                        fillColor: AppTheme.surface,
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 10,
                        ),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(
                            AppTheme.smallRadius,
                          ),
                          borderSide: const BorderSide(
                            color: AppTheme.borderSubtle,
                          ),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(
                            AppTheme.smallRadius,
                          ),
                          borderSide: const BorderSide(
                            color: AppTheme.borderSubtle,
                          ),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(
                            AppTheme.smallRadius,
                          ),
                          borderSide: const BorderSide(
                            color: AppTheme.borderHighlight,
                          ),
                        ),
                      ),
                      validator: (val) {
                        if (val == null || val.trim().isEmpty) {
                          if (ReportRepository.instance.isMockMode) {
                            return null;
                          }
                          return 'Coordinates required';
                        }
                        final parsed = double.tryParse(val);
                        if (parsed == null || parsed < -90.0 || parsed > 90.0) {
                          return '-90 to 90';
                        }
                        return null;
                      },
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Longitude *',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.secondaryText,
                      ),
                    ),
                    const SizedBox(height: 4),
                    TextFormField(
                      controller: _longitudeController,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                        signed: true,
                      ),
                      style: const TextStyle(
                        color: AppTheme.primaryText,
                        fontSize: 12,
                      ),
                      decoration: InputDecoration(
                        hintText: 'e.g. -0.1278',
                        filled: true,
                        fillColor: AppTheme.surface,
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 10,
                        ),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(
                            AppTheme.smallRadius,
                          ),
                          borderSide: const BorderSide(
                            color: AppTheme.borderSubtle,
                          ),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(
                            AppTheme.smallRadius,
                          ),
                          borderSide: const BorderSide(
                            color: AppTheme.borderSubtle,
                          ),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(
                            AppTheme.smallRadius,
                          ),
                          borderSide: const BorderSide(
                            color: AppTheme.borderHighlight,
                          ),
                        ),
                      ),
                      validator: (val) {
                        if (val == null || val.trim().isEmpty) {
                          if (ReportRepository.instance.isMockMode) {
                            return null;
                          }
                          return 'Coordinates required';
                        }
                        final parsed = double.tryParse(val);
                        if (parsed == null ||
                            parsed < -180.0 ||
                            parsed > 180.0) {
                          return '-180 to 180';
                        }
                        return null;
                      },
                    ),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  bool _isLocatingGps = false;

  Future<void> _useGpsLocation() async {
    setState(() => _isLocatingGps = true);
    try {
      final loc = await LocationService.instance.getCurrentPosition();
      if (!mounted) return;
      if (loc != null) {
        setState(() {
          _latitudeController.text = loc.latitude.toStringAsFixed(6);
          _longitudeController.text = loc.longitude.toStringAsFixed(6);
          if (_locationController.text.trim().isEmpty) {
            _locationController.text =
                'Device Location [${loc.latitude.toStringAsFixed(4)}, ${loc.longitude.toStringAsFixed(4)}]';
          }
        });
        AppToast.info(
          context,
          message: 'Coordinates populated from GPS.',
          duration: const Duration(seconds: 2),
        );
      } else {
        final err =
            LocationService.instance.errorMessage ??
            'GPS unavailable. Use "Pick on Map" or enter coordinates manually.';
        AppToast.error(
          context,
          message: err,
          duration: const Duration(seconds: 3),
        );
      }
    } finally {
      if (mounted) setState(() => _isLocatingGps = false);
    }
  }

  void _openMapLocationPicker() {
    double tempLat =
        double.tryParse(_latitudeController.text.trim()) ??
        MapConfig.defaultViewportCenter.latitude;
    double tempLon =
        double.tryParse(_longitudeController.text.trim()) ??
        MapConfig.defaultViewportCenter.longitude;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppTheme.card,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
        side: BorderSide(color: AppTheme.borderSubtle),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setModalState) {
            return SizedBox(
              height: MediaQuery.of(context).size.height * 0.75,
              child: Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 12,
                    ),
                    child: Row(
                      children: [
                        const Expanded(
                          child: Text(
                            'Select Location on Map',
                            style: TextStyle(
                              fontFamily: 'Hanken Grotesk',
                              fontSize: 15,
                              fontWeight: FontWeight.bold,
                              color: AppTheme.primaryText,
                            ),
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.close, size: 20),
                          color: AppTheme.secondaryText,
                          onPressed: () => Navigator.pop(ctx),
                        ),
                      ],
                    ),
                  ),
                  const Divider(color: AppTheme.borderSubtle, height: 1),
                  Expanded(
                    child: Stack(
                      children: [
                        FlutterMap(
                          options: MapOptions(
                            initialCenter: LatLng(tempLat, tempLon),
                            initialZoom: 14.0,
                            onTap: (tapPosition, point) {
                              setModalState(() {
                                tempLat = point.latitude;
                                tempLon = point.longitude;
                              });
                            },
                          ),
                          children: [
                            TileLayer(
                              urlTemplate: MapConfig.tileUrl,
                              userAgentPackageName: MapConfig.userAgent,
                              tileBuilder: MapConfig.darkTileBuilder,
                            ),
                            MarkerLayer(
                              markers: [
                                Marker(
                                  point: LatLng(tempLat, tempLon),
                                  width: 36,
                                  height: 36,
                                  child: Container(
                                    decoration: BoxDecoration(
                                      shape: BoxShape.circle,
                                      color: const Color(0xFF080808),
                                      border: Border.all(
                                        color: const Color(0xFFFFFFFF),
                                        width: 2,
                                      ),
                                    ),
                                    child: const Center(
                                      child: Icon(
                                        Icons.location_on,
                                        size: 18,
                                        color: Colors.white,
                                      ),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                        Positioned(
                          top: 10,
                          left: 16,
                          right: 16,
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 10,
                              vertical: 6,
                            ),
                            decoration: BoxDecoration(
                              color: AppTheme.card.withValues(alpha: 0.9),
                              borderRadius: BorderRadius.circular(
                                AppTheme.smallRadius,
                              ),
                              border: Border.all(color: AppTheme.borderSubtle),
                            ),
                            child: Text(
                              'Tap map to position pin: [${tempLat.toStringAsFixed(4)}, ${tempLon.toStringAsFixed(4)}]',
                              style: const TextStyle(
                                fontSize: 11,
                                color: AppTheme.primaryText,
                              ),
                              textAlign: TextAlign.center,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  SafeArea(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Row(
                        children: [
                          Expanded(
                            child: ElevatedButton(
                              onPressed: () {
                                setState(() {
                                  _latitudeController.text = tempLat
                                      .toStringAsFixed(6);
                                  _longitudeController.text = tempLon
                                      .toStringAsFixed(6);
                                  if (_locationController.text.trim().isEmpty) {
                                    _locationController.text =
                                        'Selected Map Pin [${tempLat.toStringAsFixed(4)}, ${tempLon.toStringAsFixed(4)}]';
                                  }
                                });
                                Navigator.pop(ctx);
                              },
                              style: ElevatedButton.styleFrom(
                                backgroundColor: AppTheme.actionPrimary,
                                foregroundColor: AppTheme.onActionPrimary,
                                padding: const EdgeInsets.symmetric(
                                  vertical: 14,
                                ),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(
                                    AppTheme.smallRadius,
                                  ),
                                ),
                              ),
                              child: const Text(
                                'Confirm Location',
                                style: TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  Widget _buildRewardSection() {
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.card,
        borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
        border: Border.all(color: AppTheme.borderSubtle),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Expanded(
                child: Row(
                  children: [
                    Icon(
                      Icons.monetization_on_outlined,
                      size: 16,
                      color: AppTheme.primaryText,
                    ),
                    SizedBox(width: 8),
                    Flexible(
                      child: Text(
                        'Offer a Reward',
                        style: TextStyle(
                          fontFamily: 'Hanken Grotesk',
                          fontSize: 14,
                          fontWeight: FontWeight.bold,
                          color: AppTheme.primaryText,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: AppTheme.surface,
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: const Text(
                  'OPTIONAL',
                  style: TextStyle(
                    fontSize: 9,
                    fontWeight: FontWeight.bold,
                    color: AppTheme.secondaryText,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          const Text(
            'Providing a finder reward is strictly optional. Rewards are settled directly during verified physical handover.',
            style: TextStyle(
              fontSize: 11.5,
              color: AppTheme.secondaryText,
              height: 1.3,
            ),
          ),
          const SizedBox(height: 12),

          // Preset amounts
          Row(
            children: ['50', '100', '250'].map((amount) {
              return Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      side: const BorderSide(color: AppTheme.borderSubtle),
                      foregroundColor: AppTheme.primaryText,
                      backgroundColor: AppTheme.surface,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(
                          AppTheme.smallRadius,
                        ),
                      ),
                    ),
                    onPressed: () {
                      setState(() => _rewardController.text = amount);
                    },
                    child: Text(
                      '\$$amount',
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
              );
            }).toList(),
          ),
          const SizedBox(height: 10),

          // Custom amount field
          TextFormField(
            controller: _rewardController,
            keyboardType: const TextInputType.numberWithOptions(decimal: false),
            style: const TextStyle(color: AppTheme.primaryText, fontSize: 13),
            decoration: InputDecoration(
              prefixText: '\$ ',
              prefixStyle: const TextStyle(
                color: AppTheme.primaryText,
                fontWeight: FontWeight.bold,
              ),
              hintText: 'Enter custom reward amount (optional)',
              hintStyle: const TextStyle(
                color: AppTheme.mutedText,
                fontSize: 12.5,
              ),
              filled: true,
              fillColor: AppTheme.surface,
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 12,
                vertical: 12,
              ),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderSubtle),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderSubtle),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderHighlight),
              ),
            ),
            validator: (val) {
              if (val == null || val.trim().isEmpty) {
                return null; // Optional
              }
              final cleaned = val
                  .replaceAll('\$', '')
                  .replaceAll('§', '')
                  .trim();
              final parsed = num.tryParse(cleaned);
              if (parsed == null) {
                return 'Please enter a valid number.';
              }
              if (parsed < 0) {
                return 'Reward cannot be negative.';
              }
              return null;
            },
          ),
        ],
      ),
    );
  }

  Widget _buildSubmissionActions(bool isMissing) {
    return Column(
      children: [
        SizedBox(
          width: double.infinity,
          height: 48,
          child: ElevatedButton(
            onPressed: _isSubmitting ? null : _submitReport,
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTheme.actionPrimary,
              foregroundColor: AppTheme.onActionPrimary,
              disabledBackgroundColor: AppTheme.surface,
              disabledForegroundColor: AppTheme.secondaryText,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              ),
            ),
            child: _isSubmitting
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      valueColor: AlwaysStoppedAnimation<Color>(Colors.black),
                    ),
                  )
                : Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Flexible(
                        child: Text(
                          isMissing
                              ? 'Publish Missing Report'
                              : 'Publish Found Report',
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.bold,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      const SizedBox(width: 8),
                      const Icon(Icons.arrow_forward, size: 16),
                    ],
                  ),
          ),
        ),
        const SizedBox(height: 10),
        SizedBox(
          width: double.infinity,
          height: 44,
          child: OutlinedButton(
            onPressed: _isSubmitting ? null : () => Navigator.of(context).pop(),
            style: OutlinedButton.styleFrom(
              foregroundColor: AppTheme.secondaryText,
              side: const BorderSide(color: AppTheme.borderSubtle),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              ),
            ),
            child: const Text('Cancel', style: TextStyle(fontSize: 13)),
          ),
        ),
      ],
    );
  }
}
