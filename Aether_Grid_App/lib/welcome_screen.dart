import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'apple_buddy.dart';

class WelcomeScreen extends StatefulWidget {
  const WelcomeScreen({
    super.key,
    required this.onPlay,
    required this.onBenchmark,
    required this.benchmarkRunning,
    required this.spatialAvailable,
    required this.preparing,
    this.initialParticipantId = '',
    this.initialBlockOrder = '',
  });

  final Future<void> Function(String participantId, String blockOrder, String mode) onPlay;
  /// Called with the selected publish QoS (0 or 1).
  final void Function(int qos) onBenchmark;
  final bool benchmarkRunning;
  final bool spatialAvailable;
  final bool preparing;
  final String initialParticipantId;
  final String initialBlockOrder;

  @override
  State<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends State<WelcomeScreen> {
  late final TextEditingController _participantController;
  late final TextEditingController _blockOrderController;
  String _mode = 'touch';
  int _benchmarkQos = 0;

  @override
  void initState() {
    super.initState();
    _participantController = TextEditingController(text: widget.initialParticipantId);
    _blockOrderController = TextEditingController(text: widget.initialBlockOrder);
  }

  @override
  void dispose() {
    _participantController.dispose();
    _blockOrderController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xff314735), Color(0xff1c2b20), Color(0xff302b22)],
          ),
        ),
        child: SafeArea(
          child: LayoutBuilder(
            builder: (context, viewport) {
              final wide = viewport.maxWidth >= 820 &&
                  viewport.maxWidth > viewport.maxHeight;
              final designWidth = wide
                  ? math.min(viewport.maxWidth, 1040.0)
                  : math.min(viewport.maxWidth, 600.0);
              // Scale down instead of scrolling when the screen (or the space
              // left over by the keyboard) is too short for the content.
              return SizedBox.expand(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: SizedBox(
                    width: designWidth,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 20,
                        vertical: 16,
                      ),
                      child: wide ? _wideLayout(context) : _narrowLayout(context),
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ),
    );
  }

  /// Landscape tablet: story on the left, form on the right.
  Widget _wideLayout(BuildContext context) => Row(
    crossAxisAlignment: CrossAxisAlignment.center,
    children: [
      Expanded(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _badge(),
            const SizedBox(height: 14),
            ..._titles(context),
            const SizedBox(height: 10),
            _apple(150),
            const SizedBox(height: 10),
            _story(),
          ],
        ),
      ),
      const SizedBox(width: 28),
      Expanded(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _participantField(),
            const SizedBox(height: 10),
            _blockOrderField(),
            const SizedBox(height: 10),
            _modeField(),
            const SizedBox(height: 18),
            _playButton(context),
            const SizedBox(height: 14),
            _benchmarkRow(),
            const SizedBox(height: 8),
            _footer(),
          ],
        ),
      ),
    ],
  );

  /// Portrait / phone: single compact column.
  Widget _narrowLayout(BuildContext context) => Column(
    mainAxisSize: MainAxisSize.min,
    children: [
      _badge(),
      const SizedBox(height: 12),
      ..._titles(context),
      const SizedBox(height: 6),
      _apple(120),
      const SizedBox(height: 6),
      _story(),
      const SizedBox(height: 14),
      Row(
        children: [
          Expanded(child: _participantField()),
          const SizedBox(width: 10),
          Expanded(child: _blockOrderField()),
        ],
      ),
      const SizedBox(height: 10),
      _modeField(),
      const SizedBox(height: 14),
      _playButton(context),
      const SizedBox(height: 10),
      _benchmarkRow(),
      const SizedBox(height: 6),
      _footer(),
    ],
  );

  Widget _badge() => DecoratedBox(
    decoration: BoxDecoration(
      color: const Color(0xff496247).withValues(alpha: .7),
      borderRadius: BorderRadius.circular(30),
      border: Border.all(
        color: const Color(0xffc9d3a6).withValues(alpha: .22),
      ),
    ),
    child: const Padding(
      padding: EdgeInsets.symmetric(horizontal: 15, vertical: 7),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.spa_rounded, color: Color(0xffd5dba9), size: 17),
          SizedBox(width: 7),
          Text(
            'A LITTLE ADVENTURE IN AETHER GROVE',
            style: TextStyle(
              color: Color(0xfff0e8d3),
              fontSize: 10,
              fontWeight: FontWeight.w800,
              letterSpacing: 1.1,
            ),
          ),
        ],
      ),
    ),
  );

  List<Widget> _titles(BuildContext context) => [
    Text(
      'Oh no, Apple is lost!',
      textAlign: TextAlign.center,
      style: Theme.of(context).textTheme.headlineLarge?.copyWith(
        color: const Color(0xfffff2dc),
        fontWeight: FontWeight.w900,
        height: 1.05,
      ),
    ),
    const SizedBox(height: 6),
    Text(
      'Can you help them find the way home?',
      textAlign: TextAlign.center,
      style: Theme.of(context).textTheme.titleMedium?.copyWith(
        color: const Color(0xffd2d9be),
      ),
    ),
  ];

  Widget _apple(double size) => SizedBox(
    width: size * 1.37,
    height: size * 1.25,
    child: Stack(
      alignment: Alignment.center,
      children: [
        Container(
          width: size * 1.12,
          height: size * 1.12,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: RadialGradient(
              colors: [
                const Color(0xff9eae7b).withValues(alpha: .27),
                const Color(0xff718c64).withValues(alpha: .02),
              ],
            ),
          ),
        ),
        Positioned(
          left: size * .06,
          top: size * .14,
          child: Transform.rotate(
            angle: -.5,
            child: Icon(
              Icons.eco_rounded,
              size: size * .21,
              color: const Color(0xffa9bf8b),
            ),
          ),
        ),
        Positioned(
          right: size * .04,
          bottom: size * .15,
          child: Transform.rotate(
            angle: .7,
            child: Icon(
              Icons.eco_rounded,
              size: size * .17,
              color: const Color(0xff829d70),
            ),
          ),
        ),
        TweenAnimationBuilder<double>(
          tween: Tween(begin: 0, end: 1),
          duration: const Duration(milliseconds: 700),
          curve: Curves.easeOutBack,
          builder: (context, value, child) => Transform.translate(
            offset: Offset(0, math.sin(value * math.pi) * -7),
            child: child,
          ),
          child: AppleBuddy(size: size),
        ),
      ],
    ),
  );

  Widget _story() => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: const Color(0xff29382d).withValues(alpha: .92),
      borderRadius: BorderRadius.circular(20),
      border: Border.all(
        color: const Color(0xffc9d3a6).withValues(alpha: .18),
      ),
      boxShadow: const [
        BoxShadow(
          color: Color(0x300c1b12),
          blurRadius: 22,
          offset: Offset(0, 10),
        ),
      ],
    ),
    child: const Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(Icons.menu_book_rounded, color: Color(0xffe2c887), size: 22),
        SizedBox(width: 12),
        Expanded(
          child: Text(
            'Apple wandered away from the orchard, and the trail home has disappeared. Guide them through Aether Grove by following the number paths. Each correct step brings Apple closer to the orchard gate!',
            style: TextStyle(
              color: Color(0xfff0e8d3),
              fontSize: 14,
              height: 1.4,
            ),
          ),
        ),
      ],
    ),
  );

  Widget _participantField() => TextField(
    controller: _participantController,
    textInputAction: TextInputAction.next,
    style: const TextStyle(color: Color(0xfffff2dc)),
    decoration: _fieldDecoration('Participant ID', 'e.g. P01'),
  );

  Widget _blockOrderField() => TextField(
    controller: _blockOrderController,
    style: const TextStyle(color: Color(0xfffff2dc)),
    decoration: _fieldDecoration(
      'Block order',
      'touch_first / gesture_first',
    ),
  );

  Widget _modeField() => DropdownButtonFormField<String>(
    value: _mode,
    isExpanded: true,
    dropdownColor: const Color(0xff29382d),
    style: const TextStyle(color: Color(0xfffff2dc)),
    decoration: _fieldDecoration('Input mode for this block', ''),
    items: [
      const DropdownMenuItem(value: 'touch', child: Text('Touch')),
      DropdownMenuItem(
        value: 'spatial',
        enabled: widget.spatialAvailable,
        child: Text(
          widget.spatialAvailable
              ? 'Spatial hand tracking'
              : 'Spatial hand tracking (camera unavailable)',
        ),
      ),
    ],
    onChanged: (value) => setState(() => _mode = value ?? 'touch'),
  );

  Widget _playButton(BuildContext context) => SizedBox(
    width: 220,
    height: 54,
    child: FilledButton.icon(
      onPressed: widget.preparing
          ? null
          : () async {
              final participant = _participantController.text.trim();
              final order = _blockOrderController.text.trim();
              if (participant.isEmpty || order.isEmpty) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text(
                      'Enter participant ID and block order before starting.',
                    ),
                  ),
                );
                return;
              }
              await widget.onPlay(participant, order, _mode);
            },
      icon: const Icon(Icons.play_arrow_rounded),
      label: Text(widget.preparing ? 'Preparing…' : 'Play'),
      style: FilledButton.styleFrom(
        backgroundColor: const Color(0xff81976b),
        foregroundColor: const Color(0xfffff5df),
        textStyle: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
        ),
        elevation: 4,
      ),
    ),
  );

  Widget _benchmarkRow() => Row(
    children: [
      SizedBox(
        width: 130,
        child: DropdownButtonFormField<int>(
          initialValue: _benchmarkQos,
          dropdownColor: const Color(0xff29382d),
          style: const TextStyle(color: Color(0xfffff2dc)),
          decoration: _fieldDecoration('Benchmark QoS', ''),
          items: const [
            DropdownMenuItem(value: 0, child: Text('QoS 0')),
            DropdownMenuItem(value: 1, child: Text('QoS 1')),
          ],
          onChanged: widget.benchmarkRunning
              ? null
              : (value) => setState(() => _benchmarkQos = value ?? 0),
        ),
      ),
      const SizedBox(width: 10),
      Expanded(
        child: OutlinedButton.icon(
          onPressed: widget.benchmarkRunning
              ? null
              : () => widget.onBenchmark(_benchmarkQos),
          icon: widget.benchmarkRunning
              ? const SizedBox.square(
                  dimension: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.speed_rounded),
          label: Text(
            widget.benchmarkRunning
                ? 'Running idle benchmark (up to 60 s)...'
                : 'Idle MQTT benchmark: 500 events at 10 Hz',
            maxLines: 2,
            textAlign: TextAlign.center,
          ),
        ),
      ),
    ],
  );

  Widget _footer() => const Text(
    'Play with touch or spatial hand controls',
    textAlign: TextAlign.center,
    style: TextStyle(color: Color(0xffbdc9ad), fontSize: 12),
  );

  InputDecoration _fieldDecoration(String label, String hint) => InputDecoration(
    labelText: label,
    hintText: hint.isEmpty ? null : hint,
    labelStyle: const TextStyle(color: Color(0xffd2d9be)),
    hintStyle: const TextStyle(color: Color(0xff9eab91)),
    filled: true,
    fillColor: const Color(0xff29382d),
    border: OutlineInputBorder(borderRadius: BorderRadius.circular(14)),
  );
}
