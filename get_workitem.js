// get_workitem.js
// Node.js script to fetch work items in the current sprint and save id, title, state, assigned to
import fs from 'fs';
import path from 'path';
import axios from 'axios';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.join(__dirname, '.env') });

const ORGANIZATION = process.env.ADO_ORG;
const PROJECT = process.env.ADO_PROJECT;
const PAT = process.env.ADO_PAT;
const TEAM = process.env.ADO_TEAM || `${PROJECT} Team`;

const ORG_ENC = encodeURIComponent(ORGANIZATION);
const PROJ_ENC = encodeURIComponent(PROJECT);
const TEAM_ENC = encodeURIComponent(TEAM);

const ITERATION_URL = `https://dev.azure.com/${ORG_ENC}/${PROJ_ENC}/${TEAM_ENC}/_apis/work/teamsettings/iterations?$timeframe=current&api-version=7.0`;
const WIQL_URL = `https://dev.azure.com/${ORG_ENC}/${PROJ_ENC}/_apis/wit/wiql?api-version=7.0`;
const WORKITEM_URL = `https://dev.azure.com/${ORG_ENC}/${PROJ_ENC}/_apis/wit/workitemsbatch?api-version=7.0`;

const OUTPUT_FILE = path.join(__dirname, 'workitems.json');

const authHeader = {
  Authorization: 'Basic ' + Buffer.from(':' + PAT).toString('base64'),
  'Content-Type': 'application/json',
  Accept: 'application/json',
};

// get team name
async function getFirstTeamName() {
  const TEAMS_URL = `https://dev.azure.com/${ORG_ENC}/_apis/projects/${PROJ_ENC}/teams?api-version=7.0`;
  const resp = await axios.get(TEAMS_URL, { headers: authHeader });
  const teams = resp.data.value;
  if (!teams || !teams.length) throw new Error('No teams found in this project.');
  return teams[0].name;
}

async function main() {
  try {
    let teamName = TEAM;
    if (!teamName) {
      teamName = await getFirstTeamName();
      console.log(`[自动获取团队名] 使用团队: ${teamName}`);
    }
    const TEAM_ENC_RUNTIME = encodeURIComponent(teamName);
    const ITERATION_URL_RUNTIME = `https://dev.azure.com/${ORG_ENC}/${PROJ_ENC}/${TEAM_ENC_RUNTIME}/_apis/work/teamsettings/iterations?$timeframe=current&api-version=7.0`;
    // get current iteration
    const resp = await axios.get(ITERATION_URL_RUNTIME, { headers: authHeader });
    const iterations = resp.data.value;
    if (!iterations || !iterations.length) throw new Error('No current iteration found.');
    const iterationPath = iterations[0].path;
    // get work item id
    const wiql = {
      query: `SELECT [System.Id] FROM WorkItems WHERE [System.IterationPath] = '${iterationPath}' ORDER BY [System.Id] ASC`,
    };
    const wiqlResp = await axios.post(WIQL_URL, wiql, { headers: authHeader });
    const ids = wiqlResp.data.workItems.map(wi => wi.id);
    // get work item details
    let details = [];
    if (ids.length) {
      const batch = {
        ids,
        fields: [
          'System.Id',
          'System.Title',
          'System.State',
          'System.AssignedTo',
        ],
      };
      const detailResp = await axios.post(WORKITEM_URL, batch, { headers: authHeader });
      details = detailResp.data.value;
    }
    const result = details.map(wi => {
      const fields = wi.fields || {};
      return {
        id: fields['System.Id'],
        title: fields['System.Title'],
        state: fields['System.State'],
        assigned_to: fields['System.AssignedTo']?.displayName || fields['System.AssignedTo'] || null,
      };
    });
    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(result, null, 2), 'utf-8');
    console.log(`Success! ${result.length} work items saved to ${OUTPUT_FILE}`);
  } catch (e) {
    console.error('Error:', e.response?.data || e.message);
  }
}

main();
