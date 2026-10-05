param(
  [string]$AcrName = "MeridianAI",
  [string]$ImageName = "meridianaiarena-backend",
  [string]$Dockerfile = "Dockerfile",
  [string]$ImageTag = "latest"
)

$ErrorActionPreference = "Stop"

Write-Host "Building backend image: $AcrName/$ImageName $ImageTag"

$imgRef = "$($ImageName):$ImageTag"
# Use az acr build to avoid docker login on CI
az acr build --registry $AcrName --image $imgRef --file $Dockerfile . 
Write-Host "Triggered build. If using --no-wait, watch build status in ACR (az acr build-task list / portal)."
