const a11yAvatar = document.getElementById('a11yAvatar');
const a11yBubble = document.getElementById('a11yBubble');
const stepsList = document.getElementById('stepsList');
const rawTaskInput = document.getElementById('rawTask');

// Actualizează starea grafică și mesajul
function setA11y(state, message) {
  a11yAvatar.className = `a11y-avatar state-${state}`;
  if (message) {
    a11yBubble.innerHTML = message;
  }
}

// Descompunere sarcini (Simulare AI pipeline)
function decomposeTask() {
  const text = rawTaskInput.value.trim();
  if (!text) return;

  // Starea: Thinking (Cameleonul devine galben și analizează)
  setA11y('thinking', 'A11y citește tichetul și elimină detaliile neesențiale...');
  stepsList.innerHTML = '<li class="step-item">Se procesează pașii...</li>';

  setTimeout(() => {
    const generatedSteps = [
      "Deschide raportul de vânzări aferent Q3.",
      "Identifică discordanțele din tabelul de cheltuieli.",
      "Extrage exclusiv rândurile care conțin erori.",
      "Trimite fișierul curat managerului până la ora 15:00."
    ];

    renderSteps(generatedSteps);
    setA11y('idle', 'Am împărțit sarcina în 4 pași simpli. Începe cu primul!');
  }, 1400);
}

// Redare checklist în UI
function renderSteps(steps) {
  stepsList.innerHTML = '';
  
  steps.forEach((stepText, index) => {
    const li = document.createElement('li');
    li.className = 'step-item';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.id = `step-${index}`;

    checkbox.addEventListener('change', (e) => {
      if (e.target.checked) {
        li.classList.add('completed');
        onStepDone(index);
      } else {
        li.classList.remove('completed');
      }
    });

    const label = document.createElement('label');
    label.htmlFor = `step-${index}`;
    label.textContent = stepText;

    li.appendChild(checkbox);
    li.appendChild(label);
    stepsList.appendChild(li);
  });
}

// Reacție la bifarea unui pas
function onStepDone(index) {
  setA11y('celebrate', `Bravo! Pasul ${index + 1} este gata! 🌟`);

  setTimeout(() => {
    setA11y('idle', 'Respiră adânc. Când ești gata, treci la următorul.');
  }, 2200);
}

// Interacțiune directă la click pe cameleon
let manualClickCount = 0;
function manualTrigger() {
  manualClickCount++;
  if (manualClickCount % 2 === 1) {
    setA11y('thinking', 'Sfat A11y: Dacă simți că te blochezi, ia o gură de apă și privește 20 de secunde pe geam.');
  } else {
    setA11y('idle', 'Sunt aici cu tine. Spor la lucru!');
  }
}

// Rulare inițială la pornire
window.addEventListener('DOMContentLoaded', () => {
  decomposeTask();
});