/* 画质增强面板逻辑（超分放大重绘 + 脸部修复）。依赖 app.js 中的 $ 与 state。 */
"use strict";

function applyQualityPreset(quality) {
  state.currentQuality = quality || {};
  const hasQuality = !!(quality && (quality.hires || quality.face_detailer));
  if (!hasQuality) {
    // 没有画质预设的模型（如部分扩散模型）默认关闭两个开关，避免空参数报错
    $("hires_fix").checked = false;
    $("face_detailer").checked = false;
    return;
  }
  const hires = quality.hires || {};
  const face = quality.face_detailer || {};
  if (hires.upscale_model && state.upscaleModels.includes(hires.upscale_model)) {
    $("upscale_model").value = hires.upscale_model;
  }
  if (hires.denoise != null) $("hires_denoise").value = hires.denoise;
  if (hires.steps != null) $("hires_steps").value = hires.steps;
  if (face.detector && $("face_detector").querySelector(`option[value="${face.detector}"]`)) {
    $("face_detector").value = face.detector;
  }
  if (face.denoise != null) $("face_denoise").value = face.denoise;
  if (face.steps != null) $("face_steps").value = face.steps;
}
