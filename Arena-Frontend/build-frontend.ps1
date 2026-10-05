param(
  [string]$AcrName = "MeridianAI",
  [string]$ImageName = "agent-framework",
  [string]$Dockerfile = "Dockerfile",
  [string]$ImageTag = "latest",
  [string]$BuildArgBackendUrl = ""
)

$ErrorActionPreference = "Stop"

Write-Host "Building frontend image: $AcrName/$ImageName $ImageTag"

$imgRef = "$($ImageName):$ImageTag"


if ($BuildArgBackendUrl -ne "") {
  Write-Host "Passing build-arg BACKEND_URL=$BuildArgBackendUrl"
  az acr build --registry $AcrName --image $imgRef --file $Dockerfile . --build-arg VITE_BACKEND_URL="$BuildArgBackendUrl" 
} else {
  Write-Host "No BACKEND_URL build-arg provided; building without."
  az acr build --registry $AcrName --image $imgRef --file $Dockerfile .
}

Write-Host "Build finished in ACR: $AcrName/$imgRef"