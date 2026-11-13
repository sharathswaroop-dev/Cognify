import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiError implements Exception {
  final String message;
  ApiError(this.message);
  @override
  String toString() => message;
}

/// A thin client over the Cognify backend: the same API the website uses.
class Api {
  static String base = 'http://192.168.66.158:8000';
  static String? token;
  static String? session; // who this phone is on the dispatch routes (signed by the server)
  static Map<String, dynamic>? user; // who is signed in: {id, name, role, tech_id?, site_id?}
  static SharedPreferences? _p;

  static Future<void> load() async {
    _p = await SharedPreferences.getInstance();
    base = _p!.getString('base') ?? base;
    token = _p!.getString('token');
    session = _p!.getString('session');
    final u = _p!.getString('user');
    if (u != null) {
      try {
        user = Map<String, dynamic>.from(jsonDecode(u) as Map);
      } catch (_) {
        user = null;
      }
    }
  }

  static Future<void> save() async {
    await _p!.setString('base', base);
    if (token == null) {
      await _p!.remove('token');
    } else {
      await _p!.setString('token', token!);
    }
    if (session == null) {
      await _p!.remove('session');
    } else {
      await _p!.setString('session', session!);
    }
    if (user == null) {
      await _p!.remove('user');
    } else {
      await _p!.setString('user', jsonEncode(user));
    }
  }

  static Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
        'X-Cognify-Session': ?session,
      };

  static Uri _uri(String path) => Uri.parse(base.replaceAll(RegExp(r'/+$'), '') + path);

  static dynamic _decode(http.Response r) {
    dynamic body;
    try {
      body = r.body.isEmpty ? null : jsonDecode(utf8.decode(r.bodyBytes));
    } catch (_) {
      body = null;
    }
    if (r.statusCode >= 400) {
      var msg = 'Something went wrong (${r.statusCode}).';
      if (body is Map && body['detail'] != null) {
        final d = body['detail'];
        msg = d is String ? d : (d is Map && d['message'] != null ? d['message'].toString() : d.toString());
      }
      throw ApiError(msg);
    }
    return body;
  }

  static Future<dynamic> get(String path) async {
    try {
      final r = await http.get(_uri(path), headers: _headers).timeout(const Duration(seconds: 40));
      return _decode(r);
    } on ApiError {
      rethrow;
    } catch (e) {
      throw ApiError('Cannot reach the server at $base. Is the laptop on the same Wi-Fi?');
    }
  }

  static Future<dynamic> post(String path, Map<String, dynamic> body) async {
    try {
      final r = await http.post(_uri(path), headers: _headers, body: jsonEncode(body)).timeout(const Duration(seconds: 120));
      return _decode(r);
    } on ApiError {
      rethrow;
    } catch (e) {
      throw ApiError('Cannot reach the server at $base. Is the laptop on the same Wi-Fi?');
    }
  }

  static Future<dynamic> upload(String path, Map<String, String> fields, String fileField, String filePath) async {
    try {
      final req = http.MultipartRequest('POST', _uri(path));
      if (token != null) req.headers['Authorization'] = 'Bearer $token';
      req.fields.addAll(fields);
      req.files.add(await http.MultipartFile.fromPath(fileField, filePath));
      final streamed = await req.send().timeout(const Duration(seconds: 120));
      return _decode(await http.Response.fromStream(streamed));
    } on ApiError {
      rethrow;
    } catch (e) {
      throw ApiError('The recording could not be sent. Check the connection and try again.');
    }
  }
}
