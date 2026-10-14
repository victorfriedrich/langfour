// @vitest-environment jsdom
//
// One synthetic page per rule of the extraction pipeline. The behaviour on
// real sites is checked by articleExtraction.corpus.test.ts.
import { describe, expect, it } from 'vitest';
import { extractArticle, LayoutVerdict } from './articleExtraction';

const URL_ = 'https://news.example.com/2026/10/story';

/** Prose long enough for Readability to take the block as an article. */
const PROSE = [
  'El ayuntamiento presentó ayer un plan para renovar la red de bibliotecas de la ciudad durante los próximos cuatro años.',
  'Según el documento, las obras empezarán por los barrios con menos servicios y se financiarán con fondos europeos.',
  'Los vecinos podrán votar en otoño qué espacios se abren primero y qué horarios prefieren para las salas de estudio.',
  'La concejala de cultura explicó que el objetivo es que ningún vecino viva a más de quince minutos de una biblioteca.',
  'El plan incluye además talleres de lectura para niños, clubes de idiomas y un servicio de préstamo de material digital.',
];

function page(article: string, outside = '', head = ''): Document {
  return new DOMParser().parseFromString(
    `<!doctype html><html lang="es"><head><title>Un plan para las bibliotecas - Diario Ejemplo</title>${head}</head>
     <body>${outside}<main><article><h1>Un plan para las bibliotecas</h1>${article}</article></main></body></html>`,
    'text/html',
  );
}

const paragraphs = (lines = PROSE) => lines.map((line) => `<p>${line}</p>`).join('');

function extract(doc: Document, layout?: (el: Element) => LayoutVerdict) {
  const article = extractArticle(doc, { url: URL_, layout });
  expect(article).not.toBeNull();
  const content = new DOMParser().parseFromString(`<div>${article!.content}</div>`, 'text/html').body;
  return { article: article!, content, text: content.textContent || '' };
}

describe('extractArticle', () => {
  it('drops consent dialogs, navigation and page chrome around the article', () => {
    const { text } = extract(page(paragraphs(), `
      <header><nav><a href="/">Portada</a><a href="/politica">Política</a></nav></header>
      <div role="dialog" aria-modal="true"><p>Aceptamos cookies para ofrecerte publicidad personalizada y medir la audiencia del sitio.</p></div>
      <aside><p>Lo más leído hoy en el diario.</p></aside>`));
    expect(text).toContain('bibliotecas de la ciudad');
    expect(text).not.toMatch(/cookies|Portada|más leído/);
  });

  it('keeps sections that are collapsed with hidden="until-found"', () => {
    const { text } = extract(page(`${paragraphs()}<section hidden="until-found"><h2>Historia</h2>${paragraphs([
      'La primera biblioteca pública de la ciudad abrió en el siglo diecinueve gracias a una donación particular.',
      'Durante décadas fue el único lugar donde los estudiantes podían consultar libros sin pagar una cuota.',
    ])}</section><section hidden><p>Este bloque está oculto de verdad y no forma parte del artículo publicado.</p></section>`));
    expect(text).toContain('siglo diecinueve');
    expect(text).not.toContain('oculto de verdad');
  });

  it('removes lists that are mostly links, such as a table of contents', () => {
    const { content } = extract(page(`<ul><li><a href="#a">Contexto</a></li><li><a href="#b">Financiación</a></li><li><a href="#c">Calendario</a></li></ul>${paragraphs()}`));
    expect(content.querySelector('ul')).toBeNull();
  });

  it('removes stray labels such as an ad slot\'s "PUBLICIDAD"', () => {
    const [a, b, ...rest] = PROSE;
    const { text } = extract(page(paragraphs([a, b]) + '<p>PUBLICIDAD</p>' + paragraphs(rest)));
    expect(text).not.toContain('PUBLICIDAD');
  });

  it('removes datelines but keeps times that start list items', () => {
    const { text } = extract(page(`<p>07/10/2026 16:00 Actualizado 18:30</p>${paragraphs()}
      <ul><li>12:40 — ¿Cuándo abrirán las nuevas salas de estudio en cada barrio?</li><li>18:05 — ¿Quién decide qué libros se compran para la colección?</li></ul>
      <p>El calendario completo se publicará en la web municipal la próxima semana, junto con los presupuestos.</p>`));
    expect(text).not.toContain('Actualizado');
    expect(text).toContain('12:40');
  });

  it('trims fragments before the first sentence and after the last', () => {
    const { text } = extract(page(`<p>Tiempo de lectura: 3 min</p>${paragraphs()}<p>Cultura</p><p>Bibliotecas</p><p>12 comentarios</p>`));
    expect(text).not.toMatch(/Tiempo de lectura|Cultura|comentarios/);
    expect(text.trim().endsWith('material digital.')).toBe(true);
  });

  it('trims closing promotions, judged by where their links go', () => {
    const { text } = extract(page(`${paragraphs()}
      <p>La información de esta noticia procede del <a href="https://www.boe.es/diario">boletín oficial</a> publicado el martes.</p>
      <div><p>Síguenos en nuestro canal para estar al día con las noticias más relevantes.</p><p><a href="https://whatsapp.com/channel/abc">Unirme</a></p></div>
      <p>No olvides <a href="/newsletter/semanal">suscribirte a nuestro boletín</a> para recibir lo mejor cada viernes.</p>`));
    expect(text).toContain('boletín oficial');
    expect(text).not.toMatch(/Síguenos|suscribirte/);
  });

  it('removes reference markers and the endnote list they point to', () => {
    const { text, content } = extract(page(`<p>${PROSE[0]}<sup>[1]</sup></p>${paragraphs(PROSE.slice(1))}
      <ol><li>↑ Plan municipal de bibliotecas, 2026.</li><li>↑ Informe de la concejalía.</li><li>↑ Encuesta vecinal.</li></ol>`));
    expect(text).not.toContain('[1]');
    expect(content.querySelector('ol')).toBeNull();
  });

  it('adds recipe ingredients from schema.org data when the text lacks them', () => {
    const recipe = { '@context': 'https://schema.org', '@type': 'Recipe', name: 'Sopa', recipeIngredient: ['2 tomates', '1 cebolla', 'Sal'] };
    const { content } = extract(page(paragraphs(), '', `<script type="application/ld+json">${JSON.stringify(recipe)}</script>`));
    expect(content.querySelector('h2')?.textContent).toBe('Ingredientes');
    expect(Array.from(content.querySelectorAll('li')).map((li) => li.textContent)).toEqual(['2 tomates', '1 cebolla', 'Sal']);
  });

  it('does not repeat ingredients that the text already lists', () => {
    const recipe = { '@type': 'Recipe', recipeIngredient: ['2 tomates', '1 cebolla'] };
    const { content } = extract(page(`${paragraphs()}<ul><li>2 tomates</li><li>1 cebolla</li></ul><p>${PROSE[0]}</p>`, '',
      `<script type="application/ld+json">${JSON.stringify({ '@graph': [recipe] })}</script>`));
    expect(content.querySelectorAll('li')).toHaveLength(2);
  });

  it('cleans the title and drops a heading that repeats it', () => {
    const { article, content } = extract(page(paragraphs()));
    expect(article.title).toBe('Un plan para las bibliotecas');
    expect(content.querySelector('h1')).toBeNull();
    expect(content.textContent).not.toContain('Un plan para las bibliotecas');
  });

  it('says there is no article when there is only a little text', () => {
    const doc = page('<p>Vídeo: el alcalde inaugura la biblioteca.</p>');
    expect(extractArticle(doc, { url: URL_ })).toBeNull();
  });

  it('uses layout, where known, to drop overlays and screen-reader-only text', () => {
    const doc = page(`<p><span class="sr">Autor,</span> ${PROSE[0]}</p>${paragraphs(PROSE.slice(1))}`,
      '<div class="cookie-bar"><p>Usamos cookies para mejorar tu experiencia en este sitio web.</p></div>');
    const layout = (el: Element): LayoutVerdict =>
      el.classList.contains('cookie-bar') ? 'overlay' : el.classList.contains('sr') ? 'screen-reader-only' : null;
    const { text } = extract(doc, layout);
    expect(text).not.toMatch(/cookies|Autor,/);
  });

  it('uses layout to drop what the page does not display', () => {
    const doc = page(`<div class="print-only"><p>Este documento se imprimió el 8 de octubre y es solo para uso personal del lector.</p></div>${paragraphs()}`);
    const layout = (el: Element): LayoutVerdict => (el.classList.contains('print-only') ? 'hidden' : null);
    const { text } = extract(doc, layout);
    expect(text).not.toContain('imprimió');
  });

  it('keeps a fixed container that holds most of the page', () => {
    const doc = page(paragraphs());
    const layout = (el: Element): LayoutVerdict => (el.tagName === 'MAIN' ? 'overlay' : null);
    const { text } = extract(doc, layout);
    expect(text).toContain('bibliotecas de la ciudad');
  });
});
