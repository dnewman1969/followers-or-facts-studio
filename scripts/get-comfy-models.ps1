<#
  Downloads the free, monetization-safe models the Studio's ComfyUI workflows use.
  Uses curl.exe (built into Windows 11); interrupted downloads resume when re-run.

      powershell -ExecutionPolicy Bypass -File .\scripts\get-comfy-models.ps1 -ComfyDir F:\AI\ComfyUI

  Z-Image Turbo (images) is already installed on Dave's PC, so it isn't downloaded here.
  About 45 GB in total (+ about 10 GB with -TextToVideo). All Apache-2.0.

      -TextToVideo   also get Wan 2.2 TI2V-5B, for b-roll clips made from words alone
#>
param([string]$ComfyDir = "F:\AI\ComfyUI", [switch]$SkipMusic, [switch]$TextToVideo)
$ErrorActionPreference = "Stop"
$m = Join-Path $ComfyDir "models"
$wan = "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files"
$wan21 = "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files"

$files = @(
    @("$wan/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "diffusion_models"),
    @("$wan/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors", "diffusion_models"),
    @("$wan/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", "loras"),
    @("$wan/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors", "loras"),
    @("$wan/vae/wan_2.1_vae.safetensors", "vae"),
    @("$wan21/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "text_encoders")
)
if ($TextToVideo) {
    $files += ,@("$wan/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors", "diffusion_models")
    $files += ,@("$wan/vae/wan2.2_vae.safetensors", "vae")
}
if (-not $SkipMusic) {
    $files += ,@("https://huggingface.co/Comfy-Org/ACE-Step_ComfyUI_repackaged/resolve/main/all_in_one/ace_step_v1_3.5b.safetensors", "checkpoints")
}

foreach ($f in $files) {
    $url, $folder = $f
    $dest = Join-Path (Join-Path $m $folder) ([IO.Path]::GetFileName($url))
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    Write-Host "-> $dest"
    curl.exe -L --fail -C - -o $dest $url
    if ($LASTEXITCODE -ne 0) { Write-Warning "Download failed: $url (check the name on the Hugging Face page and re-run)" }
}
Write-Host "Done. Restart ComfyUI so it sees the new models."
