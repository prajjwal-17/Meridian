param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"

$tests = @(
    @{
        Name = "HR Leave Policy"
        Query = "employee leave attendance payroll"
        User = "alice"
        Team = "recruitment"
        Department = "hr"
        RelevantId = 7
    },
    @{
        Name = "Engineering Development"
        Query = "Docker Kubernetes FastAPI PostgreSQL development"
        User = "bob"
        Team = "backend"
        Department = "engineering"
        RelevantId = 8
    },
    @{
        Name = "Finance Budget"
        Query = "quarterly budget operating expenses invoices"
        User = "charlie"
        Team = "finance-ops"
        Department = "finance"
        RelevantId = 9
    },
    @{
        Name = "Backend Architecture"
        Query = "Kafka asynchronous event communication API Gateway"
        User = "bob"
        Team = "backend"
        Department = "engineering"
        RelevantId = 10
    }
)

# Extract document IDs safely, including nested API result arrays.
function Get-DocumentId($Result) {

    if ($null -eq $Result) {
        return $null
    }

    if ($Result -is [array]) {
        foreach ($item in $Result) {
            $id = Get-DocumentId $item
            if ($null -ne $id) {
                return $id
            }
        }
        return $null
    }

    $value = $Result.document_id

    if ($null -eq $value) {
        return $null
    }

    return [int]$value
}

# Keep only the first occurrence of each document.
function Get-UniqueDocuments($Results) {

    $seen = @{}
    $uniqueResults = [System.Collections.Generic.List[object]]::new()

    foreach ($result in $Results) {

        $documentId = Get-DocumentId $result

        if ($null -eq $documentId) {
            continue
        }

        if (-not $seen.ContainsKey($documentId)) {
            $seen[$documentId] = $true
            $uniqueResults.Add($result)
        }
    }

    return ,$uniqueResults.ToArray()
}

# Calculate document-level metrics.
function Get-Metrics($Results, $RelevantId) {

    $rank = 0
    $position = 0

    foreach ($result in $Results) {

        $position++

        $documentId = Get-DocumentId $result

        if ($null -ne $documentId -and $documentId -eq $RelevantId) {
            $rank = $position
            break
        }
    }

    $mrr = if ($rank -gt 0) {
        1.0 / $rank
    } else {
        0.0
    }

    $ndcg = if ($rank -gt 0) {
        1.0 / ([Math]::Log($rank + 1) / [Math]::Log(2))
    } else {
        0.0
    }

    $top1 = if ($rank -eq 1) { 1 } else { 0 }

    return @{
        Rank = $rank
        MRR = $mrr
        NDCG = $ndcg
        Top1 = $top1
    }
}

function Get-Average($Metrics, $Property) {

    if ($Metrics.Count -eq 0) {
        return 0.0
    }

    $values = @(
        $Metrics | ForEach-Object {
            $_[$Property]
        }
    )

    return ($values | Measure-Object -Average).Average
}

function Show-DocumentOrder($Results) {

    if ($Results.Count -eq 0) {
        Write-Host "No documents returned."
        return
    }

    $order = @(
        foreach ($result in $Results) {
            $documentId = Get-DocumentId $result

            if ($null -ne $documentId) {
                "Doc $documentId"
            }
        }
    )

    if ($order.Count -eq 0) {
        Write-Host "No valid document IDs returned."
    } else {
        Write-Host ($order -join " -> ")
    }
}

$baselineMetrics = @()
$rerankedMetrics = @()

Write-Host "`nMERIDIAN RETRIEVAL QUALITY BENCHMARK" -ForegroundColor Cyan
Write-Host "Comparing Hybrid Retrieval vs Hybrid + Cross-Encoder`n"

foreach ($test in $tests) {

    $headers = @{
        "X-Meridian-User" = $test.User
        "X-Meridian-Team" = $test.Team
        "X-Meridian-Department" = $test.Department
    }

    $queryEncoded = [uri]::EscapeDataString($test.Query)
    $baseUri = "$BaseUrl/search?q=$queryEncoded&mode=hybrid&top_k=10"

    try {

        $baseline = Invoke-RestMethod `
            -Uri "$baseUri&rerank=false" `
            -Headers $headers `
            -Method Get

        $reranked = Invoke-RestMethod `
            -Uri "$baseUri&rerank=true" `
            -Headers $headers `
            -Method Get

        $baselineResults = @(Get-UniqueDocuments $baseline.results)
        $rerankedResults = @(Get-UniqueDocuments $reranked.results)

        $baseMetric = Get-Metrics $baselineResults $test.RelevantId
        $rerankMetric = Get-Metrics $rerankedResults $test.RelevantId

        $baselineMetrics += $baseMetric
        $rerankedMetrics += $rerankMetric

        Write-Host "`n========================================" -ForegroundColor DarkGray
        Write-Host "Query: $($test.Name)" -ForegroundColor White
        Write-Host "Search: $($test.Query)"
        Write-Host "Expected relevant document: $($test.RelevantId)"

        Write-Host "`nBaseline document order:" -ForegroundColor Cyan
        Show-DocumentOrder $baselineResults

        Write-Host "`nReranked document order:" -ForegroundColor Cyan
        Show-DocumentOrder $rerankedResults

        Write-Host "`nBaseline | Rank: $($baseMetric.Rank) | MRR: $($baseMetric.MRR.ToString('N3')) | nDCG: $($baseMetric.NDCG.ToString('N3')) | Top1: $($baseMetric.Top1)"

        Write-Host "Reranked | Rank: $($rerankMetric.Rank) | MRR: $($rerankMetric.MRR.ToString('N3')) | nDCG: $($rerankMetric.NDCG.ToString('N3')) | Top1: $($rerankMetric.Top1)"

        if ($rerankMetric.MRR -gt $baseMetric.MRR) {
            Write-Host "Improvement: YES" -ForegroundColor Green
        }
        elseif ($rerankMetric.MRR -lt $baseMetric.MRR) {
            Write-Host "Improvement: RANKING WORSENED" -ForegroundColor Red
        }
        else {
            Write-Host "Improvement: NO CHANGE" -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host "ERROR: $($test.Name) - $_" -ForegroundColor Red
        throw
    }
}

$baseMRR = Get-Average $baselineMetrics "MRR"
$rerankMRR = Get-Average $rerankedMetrics "MRR"

$baseNDCG = Get-Average $baselineMetrics "NDCG"
$rerankNDCG = Get-Average $rerankedMetrics "NDCG"

$baseTop1 = Get-Average $baselineMetrics "Top1"
$rerankTop1 = Get-Average $rerankedMetrics "Top1"

Write-Host "`n========== FINAL BENCHMARK ==========" -ForegroundColor Cyan

Write-Host ("Baseline MRR@10:  {0:N3}" -f $baseMRR)
Write-Host ("Reranked MRR@10:  {0:N3}" -f $rerankMRR)

Write-Host ("Baseline nDCG@10: {0:N3}" -f $baseNDCG)
Write-Host ("Reranked nDCG@10: {0:N3}" -f $rerankNDCG)

Write-Host ("Baseline Top-1:   {0:P1}" -f $baseTop1)
Write-Host ("Reranked Top-1:   {0:P1}" -f $rerankTop1)

Write-Host "`n========== IMPROVEMENT ==========" -ForegroundColor Cyan

Write-Host ("MRR improvement:  {0:N3}" -f ($rerankMRR - $baseMRR))
Write-Host ("nDCG improvement: {0:N3}" -f ($rerankNDCG - $baseNDCG))
Write-Host ("Top-1 improvement: {0:P1}" -f ($rerankTop1 - $baseTop1))