/* GTM Signal Plays: click tracking. Sends named events to Google Tag Manager's dataLayer.
   In GTM, add a GA4 Event tag with a Custom Event trigger for each event name below. */
(function () {
  window.dataLayer = window.dataLayer || [];
  var page = location.pathname.replace(/\/index\.html$/, '/');
  var play = (page.match(/plays\/(\d+)/) || [])[1] || 'home';
  function send(event, extra) {
    var data = { event: event, play: play, page_path: page };
    for (var k in extra) data[k] = extra[k];
    window.dataLayer.push(data);
  }
  document.addEventListener('click', function (e) {
    var el = e.target.closest('.copy, .expand, #clip, .role, .tab, .cta, .play-card, .filter, a[download]');
    if (!el) return;
    if (el.matches('.copy')) {
      var tab = document.querySelector('.tab[aria-selected="true"]');
      send('copy_prompt', { prompt_version: tab ? tab.textContent.trim() : 'default' });
    } else if (el.matches('.expand, #clip')) send('expand_diagram');
    else if (el.matches('.role')) send('role_click', { role_title: (el.querySelector('.role-t') || el).textContent.trim().slice(0, 100), link_url: el.href });
    else if (el.matches('.tab')) send('prompt_tab', { prompt_version: el.textContent.trim() });
    else if (el.matches('a[download]')) send('download_script', { file: el.getAttribute('href') });
    else if (el.matches('.cta')) send('cta_click', { cta_text: el.textContent.trim() });
    else if (el.matches('.play-card')) send('open_play', { play_card: (el.querySelector('h3') || el).textContent.trim() });
    else if (el.matches('.filter')) send('filter_click', { filter: el.textContent.trim() });
  });
})();
