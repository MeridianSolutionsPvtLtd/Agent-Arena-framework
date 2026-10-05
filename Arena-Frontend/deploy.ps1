<#
deploy.ps1 - common deploy for agent-framework apps
Usage:
  .\deploy.ps1 -Namespace ai-team -Components backend,frontend -AcrName merdianai -ImageTag v1
#>
param(
    [string[]]$Components = @("backend"),
    [string]$Namespace = "ai-team",
    [string]$ApigwNamespace = "apigw",
    [string]$ApigwServiceName = "apisix-gateway",
    [string]$AcrName = "MeridianAI",
    [string]$ImageTag = "latest",
    [string]$AcrLoginServer = "meridianai.azurecr.io",
    [string]$IngressClass = "apisix",
    [string]$BackendUrl = "",   
    [switch]$SkipRouteCreation
)

$ErrorActionPreference = "Stop"

# mapping component -> manifest names / service names / host prefix
$map = @{
    "backend"  = @{ deployment = "aks/backend-deployment.yaml"; service = "aks/backend-service.yaml"; appName="agent-framework-backend"; svcName="agent-framework-backend-service"; hostPrefix="agent-framework-backend" }
    "frontend" = @{ deployment = "aks/frontend-deployment.yaml"; service = "aks/frontend-service.yaml"; appName="agent-framework"; svcName="agent-framework-service"; hostPrefix="agent-framework" }
}

function Validate-Component($c) {
    if (-not $map.ContainsKey($c)) {
        Write-Error "Unknown component '$c'. Allowed: $($map.Keys -join ', ')"
        exit 1
    }
}

Write-Host "Deploy components: $($Components -join ', ')" -ForegroundColor Cyan

# ensure kubecontext is configured already (CI should call `az aks get-credentials` before calling this script)
# Optionally you can call az aks get-credentials here if environment has azure login (uncomment if needed)
# az aks get-credentials --resource-group <RG> --name <CLUSTER> --overwrite-existing

# Apply manifests per component
foreach ($c in $Components) {
    Validate-Component $c
    $entry = $map[$c]

    if (-not (Test-Path $entry.deployment)) {
        Write-Host "[!] Deployment manifest not found: $($entry.deployment)" -ForegroundColor Yellow
        continue
    }
    if (-not (Test-Path $entry.service)) {
        Write-Host "[!] Service manifest not found: $($entry.service)" -ForegroundColor Yellow
        continue
    }

    # Replace placeholders inline (safe rewrite)
    $d = Get-Content $entry.deployment -Raw
    $d = $d -replace '<ACR_LOGIN_SERVER>', $AcrLoginServer
    $d = $d -replace '<IMAGE_TAG>', $ImageTag

    # For frontend: optionally fill BACKEND_URL placeholder with value from parameter or env
    $urlToUse = $null
    if ($BackendUrl -ne "") { $urlToUse = $BackendUrl }
    elseif ($env:BACKEND_URL) { $urlToUse = $env:BACKEND_URL }

    # For frontend: optionally fill BACKEND_URL placeholder with real host (if preset in deployment file)
    if ($c -eq "frontend" -and $urlToUse) {
        Write-Host "Replacing BACKEND_URL placeholder with $urlToUse"
        $d = $d.Replace('<BACKEND_URL_PLACEHOLDER>', $urlToUse)
    }

    $d | Set-Content $entry.deployment -NoNewline
    kubectl apply -f $entry.deployment -n $Namespace
    kubectl apply -f $entry.service -n $Namespace

    # Ensure ClusterIP
    kubectl patch service $($entry.svcName) -n $Namespace -p '{"spec":{"type":"ClusterIP"}}' --type=merge
    kubectl get deployment $($entry.appName) -n $Namespace -o wide
    kubectl describe deployment $($entry.appName) -n $Namespace | Select-Object -First 40
    Write-Host "[+] Deployed $c" -ForegroundColor Green
}

# Wait for rollout
foreach ($c in $Components) {
    $entry = $map[$c]
    try {
        kubectl rollout status deployment/$($entry.appName) -n $Namespace --timeout=300s
    } catch {
        Write-Host "[!] Timeout or failure for deployment $($entry.appName)." -ForegroundColor Yellow
        Write-Host "=== rollout status FAILED output ==="
        kubectl get pods -n $Namespace -l app=$($entry.appName) -o wide
        kubectl describe deployment $($entry.appName) -n $Namespace
        kubectl get events -n $Namespace --sort-by='.lastTimestamp' | Select-Object -First 20
        throw $_  # rethrow so the job fails if you want CI to be red
    }
}

if ($SkipRouteCreation) { Write-Host "Skipping ApisixRoute creation." ; exit 0 }

# Create ApisixRoute(s)
$crd = kubectl get crd apisixroutes.apisix.apache.org --ignore-not-found=true
if (-not $crd) {
    Write-Host "[!] Apisix CRD not found. Skipping route creation." -ForegroundColor Yellow
    exit 0
}

$apigwSvcJson = kubectl get svc $ApigwServiceName -n $ApigwNamespace -o json 2>$null | ConvertFrom-Json
if (-not $apigwSvcJson -or -not $apigwSvcJson.status.loadBalancer.ingress) {
    Write-Host "[!] Could not find APISIX external IP. Skipping ApisixRoute creation for now." -ForegroundColor Yellow
    exit 0
}
$apigwIP = $apigwSvcJson.status.loadBalancer.ingress[0].ip
$apigwHost = $apigwSvcJson.status.loadBalancer.ingress[0].hostname

foreach ($c in $Components) {
    if ($c -ne "frontend") { continue } 
    $entry = $map[$c]
    $svcJson = kubectl get svc $($entry.svcName) -n $Namespace -o json | ConvertFrom-Json
    $servicePort = 80
    if ($svcJson.spec.ports -and $svcJson.spec.ports.Count -gt 0) { $servicePort = $svcJson.spec.ports[0].port }

    # choose host: if IP available => use nip.io; else use hostname directly
    Write-Host "Creating ApisixRoute for $($entry.appName) on port $servicePort"
    if ($apigwIP) {
        $routeHost = "$($entry.hostPrefix).$apigwIP.nip.io"
    } else {
        $routeHost = "$($entry.hostPrefix).$apigwHost"
    }


    # Define backend path prefixes to proxy to internal backend service.
    # NOTE: Adjust these to match your backend route prefixes (I included common ones).
    $backendPaths = @("/api/*") 

    # Build the ApisixRoute YAML with separate HTTP entries: backend-proxy and frontend-static
    $backendPathsYaml = ""
    foreach ($p in $backendPaths) {
        $backendPathsYaml += "          - $p`n"
    }
    # apisix route file
    $routeFile = "aks/$($entry.appName)-apisix-route.yaml"
    $routeYaml = @"
apiVersion: apisix.apache.org/v2
kind: ApisixRoute
metadata:
  name: $($entry.appName)-route
  namespace: $Namespace
spec:
  ingressClassName: $IngressClass
  http:
    - name: backend-trace-websocket
      match:
        hosts:
          - $routeHost
        paths:
          - /api/ws/trace/*
      websocket: true
      timeout:
        connect: 30s
        send: 600s
        read: 600s
      backends:
        - serviceName: agent-framework-backend-service
          servicePort: 80
    - name: backend-proxy
      match:
        hosts:
          - $routeHost
        paths:
          - /api/*
      websocket: true
      timeout:
        connect: 30s
        send: 600s
        read: 600s
      backends:
        - serviceName: agent-framework-backend-service
          servicePort: 80
    - name: $($entry.appName)
      match:
        hosts:
          - $routeHost
        paths:
          - /*
      backends:
        - serviceName: $($entry.svcName)
          servicePort: $servicePort
"@

    $routeYaml | Set-Content -Path $routeFile -NoNewline
    kubectl apply -f $routeFile -n $Namespace
    Write-Host "[+] ApisixRoute created: http://$routeHost" -ForegroundColor Green
}


Write-Host "Deployment completed."