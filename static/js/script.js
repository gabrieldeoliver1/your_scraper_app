document.addEventListener('DOMContentLoaded', function() {
    const siteForm = document.getElementById('addSiteForm');
    const termForm = document.getElementById('addTermForm');
    const searchForm = document.getElementById('searchForm');
    
    const startButton = document.getElementById('startButton');
    const stopButton = document.getElementById('stopButton');
    const currentStatusSpan = document.getElementById('currentStatus');
    const articlesContainer = document.getElementById('articles_container');

    const progressBarContainer = document.getElementById('progressBarContainer');
    const progressBar = document.getElementById('progressBar');                   

    const importSitesForm = document.getElementById('importSitesForm');
    const exportSitesButton = document.getElementById('exportSitesButton');
    const importTermsForm = document.getElementById('importTermsForm');
    const exportTermsButton = document.getElementById('exportTermsButton');
    const feedbackMessageDiv = document.getElementById('feedbackMessage');

    // --- Collapsible sections elements ---
    const toggleSitesButton = document.getElementById('toggleSites');
    const sitesContainer = document.getElementById('sitesContainer');
    const toggleTermsButton = document.getElementById('toggleTerms');
    const termsContainer = document.getElementById('termsContainer');


    let statusCheckInterval; 

    // --- Helper function to display feedback messages ---
    function showFeedback(message, isSuccess = true) {
        feedbackMessageDiv.textContent = message;
        feedbackMessageDiv.style.color = isSuccess ? 'green' : 'red';
        feedbackMessageDiv.style.display = 'block';
        setTimeout(() => {
            feedbackMessageDiv.style.display = 'none';
            feedbackMessageDiv.textContent = '';
        }, 5000); 
    }

    // --- Scraper Control Logic ---
    async function updateScraperStatus() {
        try {
            const response = await fetch('/scraper_status');
            const data = await response.json();
            
            const status = data.status.toUpperCase();
            const pagesCrawled = data.pages_crawled;
            const maxPages = data.max_pages;

            currentStatusSpan.textContent = status;

            // Update progress bar
            if (status === 'RUNNING' || status === 'STOPPING') {
                progressBarContainer.style.display = 'block';
                const percentage = maxPages > 0 ? Math.round((pagesCrawled / maxPages) * 100) : 0;
                progressBar.style.width = `${percentage}%`;
                progressBar.textContent = `${percentage}% (${pagesCrawled}/${maxPages})`;
            } else {
                progressBarContainer.style.display = 'none';
                progressBar.style.width = '0%';
                progressBar.textContent = '0%';
            }


            if (status === 'RUNNING') {
                startButton.disabled = true;
                stopButton.disabled = false;
            } else {
                // If status changes from RUNNING to STOPPED, it means it finished or was stopped.
                // In this case, automatically trigger the search to display results.
                // We check if the start button was previously disabled, indicating a running scraper.
                if (startButton.disabled === true && status === 'STOPPED') {
                    console.log("Scraper finished or stopped. Triggering automatic search...");
                    triggerSearchFormSubmission(); 
                }
                startButton.disabled = false;
                stopButton.disabled = true;
            }
        } catch (error) {
            console.error('Error fetching scraper status:', error);
            currentStatusSpan.textContent = 'ERRO';
            startButton.disabled = false; 
            stopButton.disabled = false;
            progressBarContainer.style.display = 'none';
        }
    }

    if (startButton) {
        startButton.addEventListener('click', async function() {
            startButton.disabled = true;
            stopButton.disabled = true;
            currentStatusSpan.textContent = 'INICIANDO...';
            progressBarContainer.style.display = 'block';
            progressBar.style.width = '0%';
            progressBar.textContent = '0%';
            articlesContainer.innerHTML = '<p style="text-align: center; color: #007bff;">Scraper iniciando a varredura em background. Monitore o console para ver o progresso.</p>';
            showFeedback('Scraper iniciando a varredura...', true); 
            try {
                const response = await fetch('/start_scrape', { method: 'POST' });
                const data = await response.json();
                console.log(data.status);
                if (response.status !== 202) {
                    alert(data.status); 
                    showFeedback(`Erro ao iniciar: ${data.status}`, false); 
                    updateScraperStatus();
                } else {
                    showFeedback(data.status, true); 
                    updateScraperStatus();
                }
            } catch (error) {
                console.error('Error starting scraper:', error);
                currentStatusSpan.textContent = 'FALHA AO INICIAR';
                showFeedback('Falha ao iniciar o scraper. Verifique o console.', false); 
                updateScraperStatus(); 
            }
        });
    }

    if (stopButton) {
        stopButton.addEventListener('click', async function() {
            startButton.disabled = true;
            stopButton.disabled = true;
            currentStatusSpan.textContent = 'PARANDO...';
            showFeedback('Comando de parada enviado...', true); 
            try {
                const response = await fetch('/stop_scrape', { method: 'POST' });
                const data = await response.json();
                console.log(data.status);
                showFeedback(data.status, true); 
                updateScraperStatus();
            }
            catch (error) {
                console.error('Error stopping scraper:', error);
                currentStatusSpan.textContent = 'FALHA AO PARAR';
                showFeedback('Falha ao parar o scraper. Verifique o console.', false); 
                updateScraperStatus(); 
            }
        });
    }

    // Function to trigger search form submission programmatically
    function triggerSearchFormSubmission() {
        if (searchForm) {
            articlesContainer.innerHTML = '<p style="text-align: center; color: #007bff;">Scraper finalizou. Carregando resultados...</p>';
            // Create a custom event to submit the form
            const event = new Event('submit', { bubbles: true, cancelable: true });
            searchForm.dispatchEvent(event);
        }
    }

    statusCheckInterval = setInterval(updateScraperStatus, 3000); 
    updateScraperStatus(); 

    // --- Search Form Logic ---
    if (searchForm) {
        searchForm.addEventListener('submit', function(e) {
            // No preventDefault here. The form performs a standard GET submission,
            // reloading the page with filtered results.
            articlesContainer.innerHTML = '<p style="text-align: center; color: #007bff;">Carregando notícias encontradas...</p>';
        });
    }

    // --- Import/Export Logic ---

    if (importSitesForm) {
        importSitesForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            try {
                const response = await fetch('/import_sites', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showFeedback(data.status, data.success);
                if (data.success) {
                    setTimeout(() => window.location.reload(), 1000); 
                }
            } catch (error) {
                console.error('Error importing sites:', error);
                showFeedback('Erro de rede ou servidor ao importar sites.', false);
            }
        });
    }

    if (exportSitesButton) {
        exportSitesButton.addEventListener('click', async function() {
            try {
                const response = await fetch('/export_sites');
                if (response.ok) {
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.style.display = 'none';
                    a.href = url;
                    a.download = 'sites_export.txt';
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    showFeedback('Sites exportados com sucesso!', true);
                } else {
                    const data = await response.json();
                    showFeedback(data.status, false);
                }
            } catch (error) {
                console.error('Error exporting sites:', error);
                showFeedback('Erro de rede ou servidor ao exportar sites.', false);
            }
        });
    }

    if (importTermsForm) {
        importTermsForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            try {
                const response = await fetch('/import_terms', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showFeedback(data.status, data.success);
                if (data.success) {
                    setTimeout(() => window.location.reload(), 1000); 
                }
            } catch (error) {
                console.error('Error importing terms:', error);
                showFeedback('Erro de rede ou servidor ao importar termos.', false);
            }
        });
    }

    if (exportTermsButton) {
        exportTermsButton.addEventListener('click', async function() {
            try {
                const response = await fetch('/export_terms');
                if (response.ok) {
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.style.display = 'none';
                    a.href = url;
                    a.download = 'terms_export.txt';
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    showFeedback('Termos exportados com sucesso!', true);
                } else {
                    const data = await response.json();
                    showFeedback(data.status, false);
                }
            } catch (error) {
                console.error('Error exporting terms:', error);
                showFeedback('Erro de rede ou servidor ao exportar termos.', false);
            }
        });
    }

    // --- Collapsible sections logic ---
    if (toggleSitesButton && sitesContainer) {
        toggleSitesButton.addEventListener('click', function() {
            if (sitesContainer.style.maxHeight) { 
                sitesContainer.style.maxHeight = null; 
                sitesContainer.style.padding = '0px 15px'; 
                toggleSitesButton.textContent = 'Mostrar Sites Cadastrados';
            } else {
                sitesContainer.style.maxHeight = sitesContainer.scrollHeight + "px"; 
                sitesContainer.style.padding = '15px'; 
                toggleSitesButton.textContent = 'Recolher Sites Cadastrados';
            }
        });
        // Initial state: Collapsed
        sitesContainer.style.maxHeight = null; 
        sitesContainer.style.padding = '0px 15px'; 
        toggleSitesButton.textContent = 'Mostrar Sites Cadastrados';
    }

    if (toggleTermsButton && termsContainer) {
        toggleTermsButton.addEventListener('click', function() {
            if (termsContainer.style.maxHeight) {
                termsContainer.style.maxHeight = null;
                termsContainer.style.padding = '0px 15px';
                toggleTermsButton.textContent = 'Mostrar Termos Atuais';
            } else {
                termsContainer.style.maxHeight = termsContainer.scrollHeight + "px";
                termsContainer.style.padding = '15px';
                toggleTermsButton.textContent = 'Recolher Termos Atuais';
            }
        });
        // Initial state: Collapsed
        termsContainer.style.maxHeight = null;
        termsContainer.style.padding = '0px 15px';
        toggleTermsButton.textContent = 'Mostrar Termos Atuais';
    }
});